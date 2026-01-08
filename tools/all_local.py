#!/usr/bin/env python3
### 安装

'''wget -O - https://debian.neo4j.com/neotechnology.gpg.key | sudo apt-key add -
echo 'deb https://debian.neo4j.com stable 4.4' | sudo tee -a /etc/apt/sources.list.d/neo4j.list
sudo apt-get update
sudo apt-get install neo4j
sudo systemctl start neo4j

**访问：http://localhost:7474**

**账号密码：neo4j/trim**
'''
import os
import time
import ctypes
import subprocess
import tempfile
from collections import defaultdict
from typing import List, Dict, Any, Optional

from neo4j import GraphDatabase, exceptions
from tree_sitter import Language, Parser

class GlobalConfig:
    NEO4J_URI = os.getenv("NEO4J_URI", "neo4j+s://30942530.databases.neo4j.io")
    NEO4J_AUTH = (
        os.getenv("NEO4J_USER", "neo4j"),
        os.getenv("NEO4J_PASSWORD", "6NiZaEv1hhBkOevNzb08zguuZxWChTxebS6JgaMxxFI")
    )

    # 本地的话类似于
    # NEO4J_URI = "bolt://localhost:7687"
    # NEO4J_AUTH = ("neo4j", "trim") 
    
    LIB_TREE_SITTER = './libtree-sitter-cpp.so'
    GUMTREE_HOME = os.path.expanduser("~/下载/oh-protobuf/gumtree")
    
    BATCH_SIZE = 1000
    MAX_RETRIES = 3
    
    IGNORE_DIRS = {
        '.git', 'build', 'out', 'bin', 'third_party', 'cmake', 
        'test', 'tests', 'benchmarks', 'examples', 'gumtree', 'node_modules', '.vscode'
    }
    IGNORE_SUFFIXES = (
        '.pb.cc', '.pb.h', '_test.cc', '_unittest.cc', 'mock.cc'
    )
    SOURCE_EXTENSIONS = ('.cc', '.cpp', '.cxx', '.h', '.hpp', '.c')

class BatchProcessor:
    def __init__(self, driver):
        self.driver = driver
        self.buffer = defaultdict(list)
        
        self.queries = {
            'file': "UNWIND $batch AS r MERGE (f:File {name: r.name})",
            
            'node': """
                UNWIND $batch AS r MATCH (f:File {name: r.file})
                MERGE (n:CodeNode {id: r.id})
                SET n.name = r.name, n.type = r.type, n.start = r.start, n.end = r.end, n.file = r.file
                MERGE (n)-[:BELONGS_TO]->(f)
            """,
            
            'struct_rel': """
                UNWIND $batch AS r MATCH (child:CodeNode {id: r.child})
                MATCH (parent:CodeNode {id: r.parent}) MERGE (child)-[:DECLARED_IN]->(parent)
            """,
            
            'include': """
                UNWIND $batch AS r MATCH (src:File {name: r.src})
                MATCH (target:File) WHERE target.name ENDS WITH r.inc
                MERGE (src)-[:INCLUDES]->(target)
            """,
            
            'call_temp': """
                UNWIND $batch AS r MATCH (caller:CodeNode {id: r.caller})
                MERGE (site:CallSite {hash: r.hash}) SET site.name = r.callee, site.file = r.file
                MERGE (caller)-[:CALLS]->(site)
            """,
            
            'inheritance_temp': """
                UNWIND $batch AS r MATCH (child:CodeNode {id: r.child})
                MERGE (p:BasePlaceholder {name: r.base}) MERGE (child)-[:PENDING_INHERITANCE]->(p)
            """,
            
            'macro': """
                UNWIND $batch AS r MATCH (f:File {name: r.file})
                MERGE (m:Macro {name: r.name}) MERGE (f)-[:DEFINES_MACRO]->(m)
            """,
            
            'field': """
                UNWIND $batch AS r MATCH (p:CodeNode {id: r.parent_id})
                MERGE (f:Field {name: r.name, parent: r.parent_id}) SET f.type = r.type
                MERGE (p)-[:HAS_FIELD]->(f)
            """,
            
            'param': """
                UNWIND $batch AS r MATCH (fn:CodeNode {id: r.func_id})
                MERGE (p:Parameter {name: r.name, func_id: r.func_id})
                SET p.type = r.type, p.index = r.index
                MERGE (fn)-[:HAS_PARAM {index: r.index}]->(p)
            """,
            
            'return_type': """
                UNWIND $batch AS r MATCH (fn:CodeNode {id: r.func_id})
                MERGE (t:TypeRef {name: r.type_name}) MERGE (fn)-[:RETURNS_TYPE]->(t)
            """,
            
            'comment': """
                UNWIND $batch AS r MATCH (f:File {name: r.file})
                CREATE (c:Comment {content: r.content, type: r.type, line: r.line})
                MERGE (f)-[:CONTAINS_COMMENT]->(c)
            """,
            
            'doc_link': """
                UNWIND $batch AS r MATCH (n:CodeNode {id: r.node_id})
                MATCH (f:File {name: r.file})-[:CONTAINS_COMMENT]->(c:Comment {line: r.comment_line})
                MERGE (n)-[:DOCUMENTED_BY]->(c)
            """,

            'commit': """
                UNWIND $batch AS r MERGE (a:Author {name: r.author})
                MERGE (c:Commit {hash: r.hash}) SET c.message = r.msg, c.date = r.date
                MERGE (a)-[:COMMITTED]->(c)
            """,
            'commit_file': """
                UNWIND $batch AS r MATCH (c:Commit {hash: r.hash})
                MATCH (f:File {name: r.file}) MERGE (c)-[:MODIFIED]->(f)
            """
        }

    def add(self, kind, data):
        self.buffer[kind].append(data)
        if len(self.buffer[kind]) >= GlobalConfig.BATCH_SIZE:
            self._flush_specific(kind)

    def flush_all(self):
        for kind in list(self.buffer.keys()):
            self._flush_specific(kind)

    def _flush_specific(self, kind):
        data = self.buffer[kind]
        if not data: return
        query = self.queries.get(kind)
        
        success = False
        for attempt in range(GlobalConfig.MAX_RETRIES):
            try:
                with self.driver.session() as session:
                    session.run(query, batch=data)
                success = True
                break
            except (exceptions.ServiceUnavailable, exceptions.SessionExpired, exceptions.TransientError) as e:
                wait_time = 2 ** attempt
                print(f"[Batch: {kind}] 写入中断，{wait_time}秒后重试 ({attempt+1}/{GlobalConfig.MAX_RETRIES})...")
                time.sleep(wait_time)
            except Exception as e:
                print(f"[Batch: {kind}] 错误: {e}")
                break
        
        if not success:
            print(f"[Batch: {kind}] 数据包丢失 (Size: {len(data)})")
        
        data.clear()
class IndexerEngine:
    def __init__(self, driver, project_root):
        self.driver = driver
        self.project_root = os.path.abspath(project_root)
        self.bp = BatchProcessor(driver)
        if not os.path.exists(GlobalConfig.LIB_TREE_SITTER):
            raise FileNotFoundError(f"Missing library: {GlobalConfig.LIB_TREE_SITTER}")
        lib = ctypes.CDLL(GlobalConfig.LIB_TREE_SITTER)
        lang_factory = lib.tree_sitter_cpp
        lang_factory.restype = ctypes.c_void_p
        self.parser = Parser()
        # Use new tree_sitter API (v0.21.0+): language property instead of set_language()
        self.parser.language = Language(lang_factory())

    def run_full_scan(self, force_clean=False):
        if force_clean:
            self._clean_db()
        self._init_indexes()
        
        processed = self._get_processed_files(force_clean)
        self._analyze_codebase(processed)
        self._link_relationships()
        self._analyze_git()
        self._analyze_gumtree()
        
        print("索引构建流程结束")

    def _clean_db(self):
        print("清空数据库...")
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    def _init_indexes(self):
        print("建立索引...")
        indexes = [
            "CREATE INDEX file_name IF NOT EXISTS FOR (f:File) ON (f.name)",
            "CREATE INDEX node_id IF NOT EXISTS FOR (n:CodeNode) ON (n.id)",
            "CREATE INDEX func_name IF NOT EXISTS FOR (n:CodeNode) ON (n.name)",
            "CREATE INDEX commit_hash IF NOT EXISTS FOR (c:Commit) ON (c.hash)"
        ]
        with self.driver.session() as session:
            for idx in indexes: session.run(idx)

    def _get_processed_files(self, force_clean):
        processed = set()
        if force_clean: return processed
        try:
            with self.driver.session() as session:
                res = session.run("MATCH (n:CodeNode)-[:BELONGS_TO]->(f:File) RETURN DISTINCT f.name")
                for r in res: processed.add(r["f.name"])
        except: pass
        return processed

    def _analyze_codebase(self, processed_files):
        print(f"分析代码库: {self.project_root}")
        files_to_scan = []
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in GlobalConfig.IGNORE_DIRS and not d.startswith('.')]
            if any(ign in root.split(os.sep) for ign in GlobalConfig.IGNORE_DIRS): continue
            
            for file in files:
                if file.endswith(GlobalConfig.IGNORE_SUFFIXES): continue
                if file.endswith(GlobalConfig.SOURCE_EXTENSIONS):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, self.project_root)
                    if rel_path not in processed_files:
                        files_to_scan.append((rel_path, full_path))
        
        total = len(files_to_scan)
        print(f"待处理文件: {total}")
        
        for i, (rel_path, full_path) in enumerate(files_to_scan):
            try:
                self._process_single_file(rel_path, full_path)
            except Exception as e:
                print(f"解析错误 {rel_path}: {e}")
            
            if (i+1) % 50 == 0:
                print(f" ---进度: {i+1}/{total} ---")
                self.bp.flush_all()
        self.bp.flush_all()

    def _process_single_file(self, rel_path, full_path):
        self.bp.add('file', {'name': rel_path})
        with open(full_path, 'rb') as f: code = f.read()
        tree = self.parser.parse(code)
        cursor = tree.walk()
        
        stack = []
        comments = []
        code_nodes = []
        
        reached_root = False
        while not reached_root:
            node = cursor.node
            
            if node.type == 'preproc_include':
                path_node = node.child_by_field_name('path')
                if path_node:
                    raw = code[path_node.start_byte:path_node.end_byte].decode('utf-8', errors='ignore').strip('<>"')
                    self.bp.add('include', {'src': rel_path, 'inc': raw})
            
            elif node.type == 'preproc_def':
                name_node = node.child_by_field_name('name')
                if name_node:
                    name = code[name_node.start_byte:name_node.end_byte].decode('utf-8', errors='ignore')
                    self.bp.add('macro', {'file': rel_path, 'name': name})

            elif node.type == 'comment':
                text = code[node.start_byte:node.end_byte].decode('utf-8', errors='ignore').strip()
                if text:
                    line = node.start_point[0] + 1
                    comments.append({'line': line, 'content': text})
                    self.bp.add('comment', {'file': rel_path, 'content': text, 'type': 'comment', 'line': line})

            elif node.type in {'function_definition', 'class_specifier', 'struct_specifier', 'namespace_definition'}:
                name = self._get_name(node, code)
                if name:
                    start = node.start_point[0] + 1
                    curr_id = f"{rel_path}:{name}:{start}"
                    self.bp.add('node', {
                        'id': curr_id, 'name': name, 'type': node.type,
                        'start': start, 'end': node.end_point[0] + 1, 'file': rel_path
                    })
                    code_nodes.append((start, curr_id))
                    if stack: self.bp.add('struct_rel', {'child': curr_id, 'parent': stack[-1]})
                    
                    if node.type in {'class_specifier', 'struct_specifier'}:
                        self._extract_bases(node, code, curr_id)

                    if node.type == 'function_definition':
                        self._extract_params(node, code, curr_id)
                        self._extract_return_type(node, code, curr_id)
                        
                    stack.append(curr_id)

            elif node.type == 'field_declaration' and stack:
                self._extract_field(node, code, stack[-1])

            elif node.type == 'call_expression' and stack:
                callee = self._get_call_name(node, code)
                if callee:
                    self.bp.add('call_temp', {
                        'caller': stack[-1], 'callee': callee, 
                        'hash': f"{stack[-1]}->{callee}", 'file': rel_path
                    })

            if cursor.goto_first_child(): continue
            if cursor.goto_next_sibling():
                if node.type in {'function_definition', 'class_specifier', 'struct_specifier', 'namespace_definition'}:
                    if stack: stack.pop()
                continue
            while True:
                if cursor.node.type in {'function_definition', 'class_specifier', 'struct_specifier', 'namespace_definition'}:
                    if stack: stack.pop()
                if not cursor.goto_parent(): reached_root = True; break
                if cursor.goto_next_sibling(): break
        
        for comm in comments:
            best = None
            min_dist = 6
            for n_start, n_id in code_nodes:
                if n_start > comm['line'] and (n_start - comm['line']) < min_dist:
                    min_dist = n_start - comm['line']
                    best = n_id
            if best: self.bp.add('doc_link', {'file': rel_path, 'node_id': best, 'comment_line': comm['line']})

    def _get_name(self, node, code):
        child = node.child_by_field_name('declarator') or node.child_by_field_name('name')
        if not child:
            for c in node.children:
                if c.type in ['identifier', 'type_identifier', 'field_identifier']: child = c; break
                if c.type == 'function_declarator': child = c.child_by_field_name('declarator'); break
        return code[child.start_byte:child.end_byte].decode('utf-8', errors='ignore') if child else None

    def _get_call_name(self, node, code):
        func = node.child_by_field_name('function')
        return code[func.start_byte:func.end_byte].decode('utf-8', errors='ignore') if func else None

    def _extract_bases(self, node, code, child_id):
        base_clause = node.child_by_field_name('base_class_clause')
        if base_clause:
            for child in base_clause.children:
                if child.type in ['type_identifier', 'field_expression', 'template_type', 'qualified_identifier']:
                    base_name = code[child.start_byte:child.end_byte].decode('utf-8', errors='ignore')
                    base_clean = base_name.split('::')[-1].split('<')[0].strip()
                    self.bp.add('inheritance_temp', {'child': child_id, 'base': base_clean})

    def _extract_field(self, node, code, parent_id):
        type_node = node.child_by_field_name('type')
        name_node = None
        for c in node.children:
            if c.type == 'field_identifier': name_node = c; break
        if name_node and type_node:
            name = code[name_node.start_byte:name_node.end_byte].decode('utf-8', errors='ignore')
            type_str = code[type_node.start_byte:type_node.end_byte].decode('utf-8', errors='ignore')
            self.bp.add('field', {'parent_id': parent_id, 'name': name, 'type': type_str})

    def _extract_params(self, node, code, func_id):
        declarator = node.child_by_field_name('declarator')
        if declarator:
            queue = [declarator]
            while queue:
                curr = queue.pop(0)
                if curr.type == 'parameter_list':
                    idx = 0
                    for p in curr.children:
                        if p.type == 'parameter_declaration':
                            t = p.child_by_field_name('type')
                            n = p.child_by_field_name('declarator')
                            if t:
                                ts = code[t.start_byte:t.end_byte].decode('utf-8', errors='ignore')
                                ns = code[n.start_byte:n.end_byte].decode('utf-8', errors='ignore') if n else "arg"
                                self.bp.add('param', {'func_id': func_id, 'name': ns, 'type': ts, 'index': idx})
                                idx+=1
                    break
                for c in curr.children: queue.append(c)

    def _extract_return_type(self, node, code, func_id):
        type_node = node.child_by_field_name('type')
        if type_node:
            tname = code[type_node.start_byte:type_node.end_byte].decode('utf-8', errors='ignore')
            if tname not in ['void', 'int', 'bool']:
                self.bp.add('return_type', {'func_id': func_id, 'type_name': tname})

    def _link_relationships(self):
        print("链接调用与继承关系...")
        with self.driver.session() as session:
            session.run("""
                MATCH (caller)-[:CALLS]->(site:CallSite)
                MATCH (callee:CodeNode {name: site.name}) WHERE callee.type = 'function_definition'
                MERGE (caller)-[r:INVOKES]->(callee)
                SET r.type = CASE WHEN caller.file = callee.file THEN 'INTERNAL' ELSE 'EXTERNAL' END
            """)
            session.run("MATCH (s:CallSite) DETACH DELETE s")
            session.run("""
                MATCH (child)-[:PENDING_INHERITANCE]->(p:BasePlaceholder)
                MATCH (parent:CodeNode {name: p.name}) WHERE parent.type IN ['class_specifier', 'struct_specifier']
                MERGE (child)-[:INHERITS_FROM]->(parent)
            """)
            session.run("MATCH (p:BasePlaceholder) DETACH DELETE p")

    def _analyze_git(self):
        print("分析 Git 历史...")
        try:
            cmd = ["git", "log", "--pretty=format:__SEP__|%H|%an|%ai|%s", "--name-only", "-n", "1000"]
            res = subprocess.run(cmd, cwd=self.project_root, capture_output=True, text=True, errors='replace')
            curr = None
            for line in res.stdout.splitlines():
                if line.startswith("__SEP__"):
                    p = line.split('|')
                    if len(p)>=5:
                        curr = {'hash': p[1], 'author': p[2], 'date': p[3], 'msg': p[4]}
                        self.bp.add('commit', curr)
                elif curr and line.strip() and not any(ign in line for ign in GlobalConfig.IGNORE_DIRS):
                     self.bp.add('commit_file', {'hash': curr['hash'], 'file': line.strip()})
            self.bp.flush_all()
        except Exception as e:
            print(f"Git 分析跳过: {e}")

    def _analyze_gumtree(self):
        gumtree_bin = os.path.join(GlobalConfig.GUMTREE_HOME, "bin/gumtree")
        if not os.path.exists(gumtree_bin):
            print("未找到 GumTree")
            return
        try:
            res = subprocess.run(["git", "status", "--porcelain"], cwd=self.project_root, capture_output=True, text=True)
            files = [l.split()[-1] for l in res.stdout.splitlines() if l.strip().endswith(GlobalConfig.SOURCE_EXTENSIONS)]
            
            for rel_path in files:
                if any(ign in rel_path for ign in GlobalConfig.IGNORE_DIRS): continue
                full = os.path.join(self.project_root, rel_path)
                try: old = subprocess.check_output(["git", "show", f"HEAD:{rel_path}"], cwd=self.project_root, stderr=subprocess.DEVNULL)
                except: continue

                with tempfile.NamedTemporaryFile(suffix=".cc") as tmp:
                    tmp.write(old); tmp.flush()
                    diff_res = subprocess.run([gumtree_bin, "textdiff", tmp.name, full], capture_output=True, text=True)
                    changes = []
                    for line in diff_res.stdout.splitlines():
                        if not line or "===" in line: continue
                        p = line.split()
                        try: changes.append({'action': p[0], 'line': int(p[-1])})
                        except: continue
                    
                    if changes:
                        with self.driver.session() as session:
                            session.run("""
                            MATCH (f:File {name: $fpath})
                            UNWIND $batch as row
                            CREATE (c:Change {type: row.action, line: row.line, tool: 'gumtree', timestamp: datetime()})
                            MERGE (c)-[:OCCURS_IN]->(f)
                            WITH c, row
                            MATCH (n:CodeNode {file: $fpath})
                            WHERE n.start <= row.line AND n.end >= row.line
                            WITH c, n ORDER BY (n.end - n.start) ASC LIMIT 1
                            MERGE (c)-[:AFFECTS]->(n)
                            """, fpath=rel_path, batch=changes)
        except Exception as e:
            print(f"GumTree 分析出错: {e}")

class GraphQueryService:
    def __init__(self, driver):
        self.driver = driver

    def _run(self, query, params=None):
        with self.driver.session() as session:
            result = session.run(query, params or {})
            return [dict(record) for record in result]

    def get_file_dependencies(self, file_name: str) -> List[Dict]:
        """查询文件的头文件依赖"""
        return self._run("""
        MATCH (f1:File)-[r:INCLUDES]->(f2:File) WHERE f1.name CONTAINS $name
        RETURN f1.name as source, f2.name as dependency
        """, {"name": file_name})

    def get_function_signature(self, keyword: str) -> List[Dict]:
        """模糊查询函数签名"""
        return self._run("""
        MATCH (func:CodeNode {type: 'function_definition'}) WHERE func.name CONTAINS $kw
        OPTIONAL MATCH (func)-[:HAS_PARAM]->(p:Parameter)
        OPTIONAL MATCH (func)-[:RETURNS_TYPE]->(ret)
        RETURN func.name as func, collect(p.type + ' ' + p.name) as params, ret.name as return_type
        """, {"kw": keyword})

    def get_function_callers(self, keyword: str) -> List[Dict]:
        """查询谁调用了该函数 (可模糊匹配)"""
        return self._run("""
        MATCH (caller:CodeNode)-[r:INVOKES]->(callee:CodeNode)
        WHERE callee.name CONTAINS $kw
        RETURN caller.name as caller, caller.file as file, callee.name as callee
        """, {"kw": keyword})

    def get_class_structure(self, class_name: str) -> List[Dict]:
        """查询类的内部成员变量"""
        return self._run("""
        MATCH (c:CodeNode)-[r:HAS_FIELD]->(f:Field)
        WHERE c.name CONTAINS $name
        RETURN c.name as class, f.name as field, f.type as type
        """, {"name": class_name})

    def get_class_methods(self, class_name: str) -> List[Dict]:
        """查询类包含的方法"""
        return self._run("""
        MATCH (parent:CodeNode {type: 'class_specifier'})<-[:DECLARED_IN]-(child:CodeNode {type: 'function_definition'})
        WHERE parent.name CONTAINS $name
        RETURN parent.name as class, child.name as method
        """, {"name": class_name})

    def get_indirect_impact(self, keyword: str) -> List[Dict]:
        """查询间接调用链 (Impact Analysis)"""
        return self._run("""
        MATCH (target:CodeNode {type: 'function_definition'}) WHERE target.name CONTAINS $kw
        WITH target LIMIT 5
        MATCH path = (source:CodeNode)-[:INVOKES*1..3]->(target)
        RETURN [n in nodes(path) | n.name] AS call_chain
        """, {"kw": keyword})

    def search_code_by_intent(self, keyword: str) -> List[Dict]:
        """通过 Git Message 搜索相关代码文件"""
        return self._run("""
        MATCH (a:Author)-[:COMMITTED]->(c:Commit)-[:MODIFIED]->(f:File)
        WHERE c.message CONTAINS $kw
        RETURN c.date as date, c.message as message, f.name as file
        """, {"kw": keyword})

    def get_file_history(self, file_name: str) -> List[Dict]:
        """查看文件变更历史"""
        return self._run("""
        MATCH (c:Commit)-[:MODIFIED]->(f:File) WHERE f.name CONTAINS $name
        RETURN c.date as date, c.message as msg, c.hash as commit
        """, {"name": file_name})
    
    def get_function_docs(self, function_name: str) -> List[Dict]:
        """获取函数文档/注释"""
        return self._run("""
        MATCH (n:CodeNode)-[:DOCUMENTED_BY]->(c:Comment)
        WHERE n.name CONTAINS $name
        RETURN n.name as func, c.content as doc
        """, {"name": function_name})

class CodeGraphAgent:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            GlobalConfig.NEO4J_URI, 
            auth=GlobalConfig.NEO4J_AUTH,
            max_connection_lifetime=200, keep_alive=True
        )
        self.query_service = GraphQueryService(self.driver)

    def close(self):
        self.driver.close()

    def index_project(self, project_path: str, force_clean: bool = False):
        if not os.path.exists(project_path):
            raise FileNotFoundError(f"Path not found: {project_path}")
        
        print(f"开始处理 {project_path}")
        indexer = IndexerEngine(self.driver, project_path)
        indexer.run_full_scan(force_clean=force_clean)

    def get_langchain_tools(self):
        from langchain.tools import StructuredTool
        qs = self.query_service
        return [
            StructuredTool.from_function(qs.get_file_dependencies),
            StructuredTool.from_function(qs.get_function_signature),
            StructuredTool.from_function(qs.get_function_callers),
            StructuredTool.from_function(qs.get_class_structure),
            StructuredTool.from_function(qs.get_class_methods),
            StructuredTool.from_function(qs.get_indirect_impact),
            StructuredTool.from_function(qs.search_code_by_intent),
            StructuredTool.from_function(qs.get_file_history),
            StructuredTool.from_function(qs.get_function_docs),
        ]

if __name__ == "__main__":
    agent = CodeGraphAgent()
    try:
        # 索引主项目 (可修改路径)
        target_project = "third_party_protobuf-master" 
        agent.index_project(target_project, force_clean=False) # False = 断点续传
        
        print("\n--- Testing Queries ---")
        
        print("Search 'GetMessage':")
        print(agent.query_service.get_function_signature("GetMessage")[:1])

        print("\nSearch Class 'Descriptor':")
        print(agent.query_service.get_class_methods("Descriptor")[:2])

        print("\nSearch Git 'fix':")
        print(agent.query_service.search_code_by_intent("fix")[:1])
        
    finally:
        agent.close()