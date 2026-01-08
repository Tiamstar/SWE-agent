# 动态索引系统使用指南

## 📋 概述

Harmony MAS 现在支持"动态引入、修复后删除"的索引模式：
- ✅ 自动检测项目是否已索引
- ✅ 首次运行自动建立索引
- ✅ 后续运行直接使用缓存数据
- ✅ 修复完成后可选删除项目数据
- ✅ 多项目数据完全隔离，互不干扰

## 🚀 快速开始

### 1. 运行 Harmony MAS（自动索引）

```bash
python tools/run_harmony_mas.py \
    --repo_path /path/to/project \
    --issue "Fix warning in src/main.cpp"
```

**第一次运行（未索引）：**
```
🔍 Project not indexed, building code graph...
   Repository: /path/to/project
   Project ID: a1b2c3d4e5f6g7h8
   This may take a few minutes for large projects...
⏳ 索引中...
✅ Indexing completed in 120.5 seconds
   Subsequent runs will use cached data
```

**第二次运行（已索引）：**
```
✅ Project already indexed, using cached code graph
[直接开始修复流程]
```

### 2. 运行后自动清理

```bash
python tools/run_harmony_mas.py \
    --repo_path /path/to/project \
    --issue "Fix warning" \
    --cleanup  # 修复完成后删除索引数据
```

## 📊 工作流程

### 场景 1：单个项目多次运行

```bash
# 第 1 次运行：建立索引（10 分钟）
python tools/run_harmony_mas.py --repo_path /proj1 --issue "bug1"

# 第 2 次运行：使用缓存（0 秒索引）
python tools/run_harmony_mas.py --repo_path /proj1 --issue "bug2"

# 第 3 次运行：使用缓存（0 秒索引）
python tools/run_harmony_mas.py --repo_path /proj1 --issue "bug3"

# 总索引时间：10 分钟
# 效率提升：3倍
```

### 场景 2：频繁切换项目

```bash
# 项目 A 第一次
python tools/run_harmony_mas.py --repo_path /projA --issue "fix A"  # 索引 10 分钟

# 项目 B 第一次
python tools/run_harmony_mas.py --repo_path /projB --issue "fix B"  # 索引 10 分钟

# 返回项目 A 第二次
python tools/run_harmony_mas.py --repo_path /projA --issue "fix A2"  # 使用缓存，0 秒

# 数据库状态：项目 A 和 B 的数据共存，互不干扰
```

### 场景 3：临时项目（用完即删）

```bash
# 修复临时项目
python tools/run_harmony_mas.py \
    --repo_path /tmp/temp_project \
    --issue "quick fix" \
    --cleanup  # 完成后自动删除索引数据

# 数据库保持干净
```

## 🔧 手动索引管理

### 手动建立索引

```bash
# 为项目建立索引
/workspaces/SWE-agent/tools/harmony_graph/bin/code_indexer /path/to/project

# 强制重建索引（清除旧数据）
/workspaces/SWE-agent/tools/harmony_graph/bin/code_indexer /path/to/project --force-clean
```

### 手动删除项目数据

```python
from tools.harmony_graph.lib.core import CodeGraphAgent
import hashlib

# 生成 project_id
repo_path = "/path/to/project"
project_id = hashlib.sha256(repo_path.encode()).hexdigest()[:16]

# 删除数据
agent = CodeGraphAgent()
agent.delete_project(project_id)
agent.close()
```

### 查询现有项目

```python
from tools.harmony_graph.lib.core import CodeGraphAgent

agent = CodeGraphAgent()

# 检查项目是否已索引
project_id = "a1b2c3d4e5f6g7h8"
if agent.is_project_indexed(project_id):
    print("Project is indexed")
else:
    print("Project not indexed")

agent.close()
```

## 🎯 最佳实践

### 开发阶段（保留数据）

```bash
# 不使用 --cleanup，索引数据保留
python tools/run_harmony_mas.py --repo_path /dev/project --issue "bug1"
python tools/run_harmony_mas.py --repo_path /dev/project --issue "bug2"
python tools/run_harmony_mas.py --repo_path /dev/project --issue "bug3"

# 优势：后续运行秒级启动，开发效率高
```

### 生产环境（定期清理）

```bash
# 使用 --cleanup，修复完成后清理
python tools/run_harmony_mas.py \
    --repo_path /prod/project \
    --issue "prod bug" \
    --cleanup

# 优势：数据库保持干净，避免占用过多空间
```

### CI/CD 集成

```yaml
# .github/workflows/harmony-mas.yml
- name: Run Harmony MAS
  run: |
    python tools/run_harmony_mas.py \
      --repo_path ${{ github.workspace }} \
      --issue "${{ github.event.issue.title }}" \
      --cleanup  # CI/CD 环境中总是清理
```

## 📐 架构说明

### Project ID 生成

```python
import hashlib

# 基于绝对路径生成唯一 ID
repo_path = "/path/to/project"
project_id = hashlib.sha256(repo_path.encode()).hexdigest()[:16]

# 示例：a1b2c3d4e5f6g7h8
```

### 数据隔离机制

所有 Neo4j 节点和关系都带有 `project_id` 属性：

```cypher
// 索引时
MERGE (f:File {name: 'src/main.cpp', project_id: 'a1b2c3d4e5f6g7h8'})

// 查询时（自动过滤）
MATCH (f:File {project_id: 'a1b2c3d4e5f6g7h8'})
WHERE f.name CONTAINS 'main'
RETURN f
```

### 环境变量

```bash
# SWE-ReX 容器中自动设置
HARMONY_PROJECT_ID=a1b2c3d4e5f6g7h8
NEO4J_URI=bolt://swe-agent_devcontainer-neo4j-1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=swe-agent-local
```

## ⚙️ 配置选项

### run_harmony_mas.py 参数

```bash
python tools/run_harmony_mas.py \
    --repo_path /path/to/repo          # 必需：仓库路径
    --issue "Fix warning"              # 必需：问题描述
    --cleanup                          # 可选：完成后删除索引数据
    --max_iterations 3                 # 可选：最大迭代次数
    --num_candidate_patches 3          # 可选：候选补丁数量
    --image python:3.11                # 可选：Docker 镜像
```

### code_indexer 参数

```bash
/tools/harmony_graph/bin/code_indexer \
    /path/to/repo                      # 仓库路径
    --force-clean                      # 强制重建索引
    --project-id custom_id             # 自定义 project_id
```

## 🔍 故障排查

### 索引失败

```bash
# 检查 Neo4j 连接
python3 -c "
from neo4j import GraphDatabase
driver = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'swe-agent-local'))
driver.verify_connectivity()
print('✓ Neo4j connected')
"
```

### 查询工具报错

```bash
# 检查环境变量
echo $HARMONY_PROJECT_ID
echo $NEO4J_URI

# 手动设置
export HARMONY_PROJECT_ID=a1b2c3d4e5f6g7h8
```

### 数据库占用过大

```python
# 查询所有项目
from neo4j import GraphDatabase

driver = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j', 'swe-agent-local'))
with driver.session() as session:
    result = session.run("MATCH (f:File) RETURN DISTINCT f.project_id, count(*) as files ORDER BY files DESC")
    for record in result:
        print(f"Project: {record['f.project_id']}, Files: {record['files']}")
driver.close()
```

## 📈 性能对比

| 场景 | 无缓存（方案B） | 有缓存（优化后的方案A） | 效率提升 |
|------|----------------|---------------------|---------|
| 同一项目运行 3 次 | 30 分钟 | 10 分钟 | **3倍** |
| 5 个项目各运行 2 次 | 100 分钟 | 50 分钟 | **2倍** |
| 长期使用（次月） | 100 分钟 | 0 分钟 | **∞倍** |

## ✅ 总结

- ✨ **零配置**：首次运行自动索引
- 🚀 **高效率**：缓存复用，避免重复索引
- 🧹 **可清理**：使用 `--cleanup` 保持数据库干净
- 🔒 **数据隔离**：多项目互不干扰
- 💡 **灵活控制**：开发时保留，生产时清理
