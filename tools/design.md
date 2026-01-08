本指南将一步步指导您将现有的 `all_local.py` 转化为 `swe-agent` 标准工具包。

-----

# HarmonyOS Code Graph 工具包集成指南

## 1\. 架构设计概览

我们将采用 **"One Binary, Many Tools"（单执行体，多工具接口）** 的设计模式。

  * **后端 (Backend)**: 您的 Neo4j 数据库 + `all_local.py` (作为核心库)。
  * **中间件 (Middleware)**: `bin/code_graph`，一个 Python CLI 包装器，负责路由指令并输出 JSON。
  * **前端 (Interface)**: `config.yaml`，将底层指令拆解为 8+ 个语义化工具，分别提供给不同的 Agent 使用。

-----

## 2\. 目录结构 (Directory Structure)

请在您的 `swe-agent` 工具目录下创建一个名为 `harmony_graph` 的文件夹，结构如下：

```text
harmony_graph/
├── bin/
│   ├── code_graph        # [核心] 主 CLI 入口，处理查询请求
│   └── code_indexer      # [辅助] 用于初始化构建索引的脚本
├── lib/
│   ├── __init__.py       # 空文件，使 lib 成为 Python 包
│   ├── core.py           # 原 all_local.py 重命名为此，并做微调
│   └── libtree-sitter-cpp.so # 编译好的 Tree-sitter 库
├── config.yaml           # [核心] 定义给 LLM 看的工具列表
├── install.sh            # 安装 Python 依赖和环境配置
├── pyproject.toml        # (可选) Python 项目定义
└── README.md             # 说明文档
```

-----

## 3\. 详细实施步骤

### 第一步：改造核心库 (`lib/core.py`)

将您上传的 `all_local.py` 移动到 `lib/core.py`。为了让它能被 `bin/code_graph` 导入且不自动运行，需要做以下修改：

1.  **移除文件末尾的 `if __name__ == "__main__":` 块**，或者将其注释掉。
2.  **动态化配置**：修改 `GlobalConfig` 类，使其优先读取环境变量。

<!-- end list -->

```python
# lib/core.py (原 all_local.py 的修改版)

import os
# ... 其他导入保持不变 ...

class GlobalConfig:
    # 允许通过环境变量覆盖，方便容器化部署
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687") # 默认改为本地或容器别名
    NEO4J_AUTH = (
        os.getenv("NEO4J_USER", "neo4j"),
        os.getenv("NEO4J_PASSWORD", "trim") # 默认密码
    )
    
    # 动态定位 lib 目录下的 .so 文件
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    LIB_TREE_SITTER = os.path.join(CURRENT_DIR, 'libtree-sitter-cpp.so')
    
    # ... 其他配置保持不变 ...

# ... 保持 BatchProcessor, IndexerEngine, GraphQueryService 类不变 ...

# 确保 CodeGraphAgent 可以被外部导入
class CodeGraphAgent:
    # ... 保持不变 ...
```

### 第二步：编写 CLI 入口 (`bin/code_graph`)

这是连接 Agent 和代码逻辑的桥梁。创建 `bin/code_graph` 文件：

```python
#!/usr/bin/env python3
import sys
import os
import json
import argparse
import traceback

# 1. 将 lib 目录加入系统路径，以便导入 core.py
bin_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(bin_dir)
lib_dir = os.path.join(root_dir, 'lib')
sys.path.append(lib_dir)

# 2. 导入核心类
try:
    from core import CodeGraphAgent
except ImportError as e:
    # 将错误输出到 stderr，避免污染 stdout 的 JSON 结果
    sys.stderr.write(f"Critical Error: Failed to import core library. {e}\n")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser()
    # 定义主命令参数
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- 拓扑类命令 ---
    subparsers.add_parser("dependencies").add_argument("file_name")
    subparsers.add_parser("structure").add_argument("class_name")
    subparsers.add_parser("methods").add_argument("class_name")

    # --- 时序类命令 ---
    subparsers.add_parser("history").add_argument("file_name")
    subparsers.add_parser("intent_search").add_argument("keyword")

    # --- 契约类命令 ---
    subparsers.add_parser("signature").add_argument("func_name")
    subparsers.add_parser("docs").add_argument("func_name")

    # --- 影响类命令 ---
    subparsers.add_parser("impact").add_argument("func_name")
    subparsers.add_parser("callers").add_argument("func_name")

    args = parser.parse_args()

    # 初始化 Agent
    agent = None
    try:
        agent = CodeGraphAgent()
        qs = agent.query_service
        result = []

        # 路由逻辑
        if args.command == "dependencies":
            result = qs.get_file_dependencies(args.file_name)
        elif args.command == "structure":
            result = qs.get_class_structure(args.class_name)
        elif args.command == "methods":
            result = qs.get_class_methods(args.class_name)
        elif args.command == "history":
            result = qs.get_file_history(args.file_name)
        elif args.command == "intent_search":
            result = qs.search_code_by_intent(args.keyword)
        elif args.command == "signature":
            result = qs.get_function_signature(args.func_name)
        elif args.command == "docs":
            result = qs.get_function_docs(args.func_name)
        elif args.command == "impact":
            result = qs.get_indirect_impact(args.func_name)
        elif args.command == "callers":
            result = qs.get_function_callers(args.func_name)

        # [关键] 结果必须是 JSON 格式，且输出到 stdout
        print(json.dumps(result, indent=2, ensure_ascii=False))

    except Exception as e:
        # 捕捉异常并以 JSON 格式返回错误，避免 Agent 解析崩溃
        error_msg = {"error": str(e), "trace": traceback.format_exc()}
        print(json.dumps(error_msg))
    finally:
        if agent:
            agent.close()

if __name__ == "__main__":
    main()
```

*注意：请运行 `chmod +x bin/code_graph` 赋予执行权限。*

### 第三步：编写工具定义 (`config.yaml`)

这是您的核心需求所在。我们将工具按 Agent 职责进行分组，使得每个 Agent 只能看到和使用与其任务相关的工具。

```yaml
tools:
  # =================================================================
  # 1. 拓扑分析 Agent (Topology Agent) 工具集
  # 目标：解析静态结构、文件依赖、类图
  # =================================================================
  - name: inspect_file_topology
    command: code_graph dependencies {{file_name}}
    description: >
      Analyzes the physical dependencies of a file (e.g., #include headers). 
      Use this to determine module coupling before making changes.
    arguments:
      file_name:
        type: string
        description: Relative path of the source file (e.g., 'foundation/ace/adapter.cpp').

  - name: inspect_class_schema
    command: code_graph structure {{class_name}}
    description: >
      Retrieves the internal structure of a class, including member variables (fields) and types.
    arguments:
      class_name:
        type: string
        description: The exact name of the class.

  - name: list_class_methods
    command: code_graph methods {{class_name}}
    description: >
      Lists all methods declared within a specific class. 
      Helpful to get an overview of class capabilities.
    arguments:
      class_name:
        type: string
        description: The exact name of the class.

  # =================================================================
  # 2. 时序感知 Agent (Temporal Agent) 工具集
  # 目标：挖掘变更历史、开发者意图、热点代码
  # =================================================================
  - name: search_historical_intent
    command: code_graph intent_search {{keyword}}
    description: >
      Searches git commit messages for semantic keywords (e.g., "fix memory leak", "refactor ipc").
      Use this to find how similar bugs were fixed in the past.
    arguments:
      keyword:
        type: string
        description: The intent keyword or phrase to search for.

  - name: view_file_changelog
    command: code_graph history {{file_name}}
    description: >
      Retrieves the recent git commit history for a specific file.
      Use this to identify who modified the file recently and why.
    arguments:
      file_name:
        type: string
        description: The file path to inspect.

  # =================================================================
  # 3. 契约验证 Agent (Contract Agent) 工具集
  # 目标：确保接口一致性、类型安全、符合文档规范
  # =================================================================
  - name: verify_func_signature
    command: code_graph signature {{func_name}}
    description: >
      [CRITICAL] Returns the exact function signature (param types, return type).
      MUST be used before generating patches to ensure type consistency.
    arguments:
      func_name:
        type: string
        description: The name of the function/method.

  - name: read_func_documentation
    command: code_graph docs {{func_name}}
    description: >
      Reads the documentation/comments associated with a function.
      Use this to understand the "logical contract" and preconditions.
    arguments:
      func_name:
        type: string
        description: The name of the function.

  # =================================================================
  # 4. 影响传播 Agent (Impact Agent) 工具集
  # 目标：风险预警、调用链分析
  # =================================================================
  - name: trace_downstream_impact
    command: code_graph impact {{func_name}}
    description: >
      Analyzes the call chain to see what downstream functions are called by the target.
      Use this to estimate the "spread" of your logic changes.
    arguments:
      func_name:
        type: string
        description: The root function name to trace.

  - name: find_upstream_callers
    command: code_graph callers {{func_name}}
    description: >
      Identifies all functions that invoke the target function.
      Use this to check if changing the target will break existing clients.
    arguments:
      func_name:
        type: string
        description: The callee function name.
```

### 第四步：编写安装脚本 (`install.sh`)

此脚本将在 `swe-agent` 容器启动或工具安装时运行。

```bash
#!/bin/bash
set -e

echo "Starting HarmonyOS Graph Tool installation..."

# 1. 安装 Python 依赖
# 注意：all_local.py 依赖 neo4j 和 tree-sitter
pip install neo4j tree-sitter

# 2. 确保 Tree-sitter 的 .so 库存在
# 情况 A: 如果你已经在宿主机编译好并放入了 lib/ 文件夹，这里只需检查
if [ ! -f "lib/libtree-sitter-cpp.so" ]; then
    echo "Warning: libtree-sitter-cpp.so not found in lib/."
    echo "Attempting to download or compile... (这里可以添加自动编译逻辑)"
    # 简化的自动编译逻辑示例：
    # git clone https://github.com/tree-sitter/tree-sitter-cpp
    # gcc -shared -o lib/libtree-sitter-cpp.so -I tree-sitter-cpp/src tree-sitter-cpp/src/parser.c tree-sitter-cpp/src/scanner.cc -lstdc++
fi

# 3. 设置执行权限
chmod +x bin/code_graph
chmod +x bin/code_indexer

echo "Installation complete."
```

### 第五步：初始化索引 (`bin/code_indexer`)

在 Agent 真正开始工作前，需要建立图谱。可以单独提供这个脚本。

```python
#!/usr/bin/env python3
import sys
import os

# 路径设置同 code_graph
bin_dir = os.path.dirname(os.path.abspath(__file__))
lib_dir = os.path.join(os.path.dirname(bin_dir), 'lib')
sys.path.append(lib_dir)

from core import CodeGraphAgent

if __name__ == "__main__":
    # 获取当前工作目录（swe-agent 通常在仓库根目录运行）
    repo_path = os.getcwd()
    print(f"Initializing graph index for: {repo_path}")
    
    agent = CodeGraphAgent()
    try:
        # force_clean=True 建议在第一次运行时开启，重建整个图
        agent.index_project(repo_path, force_clean=False)
        print("Graph indexing completed successfully.")
    except Exception as e:
        print(f"Indexing failed: {e}")
    finally:
        agent.close()
```

-----

## 4. 如何在多 Agent 系统中使用

完成上述配置后，您的系统工作流如下：

1.  **启动阶段**:

      * 启动 Neo4j 服务。
      * 在目标代码仓库根目录运行 `harmony_graph/bin/code_indexer`，构建初始图谱。

2.  **调度阶段 (Orchestrator)**:

      * 当需要修复 Bug 时，调度器唤醒 **时序感知 Agent**。
      * Agent 看到 `search_historical_intent` 工具，输入 "memory leak"，获取历史 Commit。

3.  **分析阶段**:

      * 调度器唤醒 **拓扑分析 Agent**。
      * Agent 使用 `inspect_class_schema` 查看相关类的结构。

4.  **验证阶段**:

      * 调度器唤醒 **契约验证 Agent**。
      * Agent 准备修改代码前，强制调用 `verify_func_signature`，确保参数类型正确。

5.  **评估阶段**:

      * **影响传播 Agent** 使用 `find_upstream_callers`，警告修改可能导致上层模块崩溃。

通过这份文档，您已经成功将原本独立的分析脚本转化为了一个企业级、语义化的智能体工具包。