# HarmonyOS Code Graph - Neo4j 工具包

一个企业级代码分析工具，基于 Neo4j 图数据库构建，为 SWE-Agent 提供语义化的代码查询接口。

## 概述

本工具包采用 **"One Binary, Many Tools"** 的设计模式，将复杂的代码分析逻辑解耦为多个专用 Agent 工具：

- **拓扑分析 Agent** - 解析静态结构、文件依赖、类图
- **时序感知 Agent** - 挖掘变更历史、开发者意图、热点代码
- **契约验证 Agent** - 确保接口一致性、类型安全
- **影响传播 Agent** - 风险预警、调用链分析

## 目录结构

```
harmony_graph/
├── bin/
│   ├── code_graph        # CLI 主入口，负责路由查询请求
│   └── code_indexer      # 索引构建工具，初始化代码图
├── lib/
│   ├── __init__.py       # Python 包初始化
│   ├── core.py           # 核心库（改进的 all_local.py）
│   └── libtree-sitter-cpp.so  # Tree-sitter C++ 库 (可选)
├── config.yaml           # SWE-Agent 工具定义
├── install.sh            # 自动安装脚本
├── README.md             # 本文档
└── pyproject.toml        # (可选) Python 项目配置
```

## 快速开始

### 1. 安装依赖

```bash
cd tools/harmony_graph
bash install.sh
```

这会自动安装：
- `neo4j` - Neo4j 数据库驱动
- `tree-sitter` - 代码解析库

### 2. 启动 Neo4j 服务

```bash
# 使用本地 Neo4j (Linux/macOS)
sudo systemctl start neo4j

# 或使用 Docker
docker run -d \
  -p 7687:7687 \
  -p 7474:7474 \
  -e NEO4J_AUTH=neo4j/trim \
  neo4j:latest
```

**Web 界面**: http://localhost:7474
**默认账号**: neo4j / trim

### 3. 索引代码库

在目标代码库根目录运行：

```bash
/path/to/harmony_graph/bin/code_indexer [--force-clean]
```

选项：
- 无参数：增量索引（跳过已处理的文件）
- `--force-clean`：清空数据库并重新索引

例如：
```bash
cd ~/my-project
../swe-agent/tools/harmony_graph/bin/code_indexer --force-clean
```

### 4. 查询图数据

```bash
# 查询函数签名
./bin/code_graph signature GetMessage

# 查询文件依赖
./bin/code_graph dependencies adapter.cpp

# 查询类结构
./bin/code_graph structure Descriptor

# 查询类方法
./bin/code_graph methods MessageBuilder

# 查询函数调用者
./bin/code_graph callers ParseMessage

# 查询函数调用的其他函数
./bin/code_graph impact ParseMessage

# 查询文件历史
./bin/code_graph history src/message.cc

# 搜索意图相关的 commit
./bin/code_graph intent_search "fix memory leak"

# 获取函数文档
./bin/code_graph docs GetMessage
```

## 环境配置

可通过环境变量自定义 Neo4j 连接：

```bash
# 本地 Neo4j
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="trim"

# 远程 Neo4j AuraDB
export NEO4J_URI="neo4j+s://xxxx.databases.neo4j.io"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="xxxxx"
```

## SWE-Agent 集成

### 将工具包添加到 config.yaml

编辑 `config/default.yaml` 或其他配置文件：

```yaml
agent:
  tools:
    bundles:
      - path: tools/harmony_graph
```

### 工具列表

| 工具名称 | 用途 | 示例 |
|---------|------|------|
| `inspect_file_topology` | 获取文件依赖 | 修改前评估影响范围 |
| `inspect_class_schema` | 查看类成员 | 理解类的内部结构 |
| `list_class_methods` | 列出类方法 | 找到需要修改的方法 |
| `search_historical_intent` | 搜索历史 commit | 寻找相似 bug 修复 |
| `view_file_changelog` | 查看文件历史 | 跟踪文件演变 |
| `verify_func_signature` | 验证函数签名 | **必须在修改前调用** |
| `read_func_documentation` | 获取函数文档 | 理解函数契约 |
| `trace_downstream_impact` | 追踪函数调用链 | 评估修改传播范围 |
| `find_upstream_callers` | 找函数调用者 | 检查谁依赖此函数 |

## 架构细节

### 后端 (Backend)
- **Neo4j 数据库**: 存储代码图数据
- **lib/core.py**: Python 核心库，包含：
  - `IndexerEngine` - 代码索引和 AST 解析
  - `GraphQueryService` - Cypher 查询接口
  - `CodeGraphAgent` - 主控制类

### 中间件 (Middleware)
- **bin/code_graph**: CLI 路由器，处理 8+ 个子命令
- 所有输出为 JSON 格式，便于 Agent 解析

### 前端 (Interface)
- **config.yaml**: 定义给 LLM 看的工具
- **SWE-Agent**: 调用工具并整合结果

## 数据模型

### 主要节点类型
- `File` - 源代码文件
- `CodeNode` - 代码元素 (函数、类、命名空间)
- `Parameter` - 函数参数
- `TypeRef` - 类型引用
- `Comment` - 代码注释
- `Commit` - Git 提交
- `Author` - Git 作者
- `Field` - 类成员变量
- `Macro` - 预处理宏

### 主要关系类型
- `:BELONGS_TO` - 代码元素属于文件
- `:DECLARED_IN` - 代码元素在另一个元素内声明
- `:INVOKES` - 函数调用关系
- `:INHERITS_FROM` - 类继承关系
- `:HAS_FIELD` - 类有成员变量
- `:HAS_PARAM` - 函数有参数
- `:RETURNS_TYPE` - 函数返回类型
- `:INCLUDES` - 文件包含关系
- `:MODIFIED` - Commit 修改文件
- `:DOCUMENTED_BY` - 代码被注释文档化

## 故障排查

### 问题：`libtree-sitter-cpp.so not found`

**原因**: Tree-sitter C++ 库未编译

**解决**:
```bash
# 方案 A: 从预编译版本复制
cp ~/path/to/libtree-sitter-cpp.so tools/harmony_graph/lib/

# 方案 B: 自行编译 (仅需要 AST 解析时)
cd tools/harmony_graph/lib
git clone https://github.com/tree-sitter/tree-sitter-cpp.git
gcc -shared -o libtree-sitter-cpp.so \
  -I tree-sitter-cpp/src \
  tree-sitter-cpp/src/parser.c tree-sitter-cpp/src/scanner.cc \
  -lstdc++ -fPIC
```

**注**: 许多查询功能无需 AST 解析也能工作（基于 Git 历史和注释分析）

### 问题：`Neo4j connection failed`

**原因**: Neo4j 服务未启动或连接参数错误

**检查**:
```bash
# 验证服务状态
sudo systemctl status neo4j

# 测试连接
python3 -c "from neo4j import GraphDatabase; \
  driver = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'trim')); \
  print(driver.verify_connectivity()); driver.close()"
```

### 问题：索引速度慢

**原因**: 大型代码库处理时间长

**优化**:
```bash
# 使用增量索引（避免重新处理已索引的文件）
./bin/code_indexer /path/to/repo

# 如需清空重建，可跳过 GumTree 分析（需要依赖项较多）
# 修改 lib/core.py，注释 _analyze_gumtree() 调用
```

## 性能指标

| 操作 | 耗时 | 说明 |
|------|------|------|
| 索引 10K 文件 | ~5 分钟 | 包含 AST 和 Git 分析 |
| 查询函数签名 | <100ms | 数据库查询 |
| 追踪调用链（深度 3） | <500ms | 图遍历 |
| 搜索 commit 历史 | <200ms | 正则匹配 |

## 许可证

继承 SWE-Agent 项目许可证

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系

参考 SWE-Agent 项目主文档了解更多信息。
