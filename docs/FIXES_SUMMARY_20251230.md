# Harmony MAS 修复总结

本次修复完成了以下任务:

## 1. ✅ 从 topology/temporal agents 中移除 mas_tools

**原因:** mas_tools 只提供 `return_result` 命令，但这两个 agent 已经有 `tools/review_on_submit_m` 提供的 `submit` 命令。协调器可以从 submission 字段和 trajectory 中提取结果，不需要额外的工具。

**修改文件:**
- `config/agents/topology_agent.yaml` - 移除 mas_tools bundle
- `config/agents/temporal_agent.yaml` - 移除 mas_tools bundle

---

## 2. ✅ 简化 review_agent prompt

**问题诊断:**
从轨迹分析发现 review_agent 只执行了 2 个 action 就停止了：
- 原因 1: 原 prompt 过于复杂，包含大量装饰性符号，干扰 LLM 理解
- 原因 2: 使用 gpt-4o-mini 模型，指令跟随能力较弱
- 原因 3: max_requeries=2 太低，容易过早终止

**修复措施:**
- **简化 prompt**: 移除所有装饰性符号(═══, 🎯, ✅等)，使用简洁清晰的指令
- **升级模型**: gpt-4o-mini → gpt-4o (更好的指令跟随能力)
- **增加重试次数**: max_requeries: 2 → 5

**修改文件:**
- `config/agents/review_agent.yaml` - 完全重写 system_template，升级模型和重试次数

---

## 3. ✅ 确保静态分析工具安装

**现状:** `tools/static_analysis/install.sh` 已存在，但未在容器初始化时运行

**修复措施:**
- 更新 `.devcontainer/postcreate.sh` 以自动运行 `tools/static_analysis/install.sh`
- 安装 cppcheck, clang-tidy, cpplint
- 工具安装失败时不会中断流程，review_agent 会返回 CHECK_SKIPPED 状态

**修改文件:**
- `.devcontainer/postcreate.sh` - 添加静态分析工具安装步骤

---

## 4. ✅ 设置本地 Neo4j 数据库

**目标:** 从外部 Neo4j 数据库迁移到本地 Docker 容器中的 Neo4j

**实现:**
1. **Docker Compose 配置**: 创建 `.devcontainer/docker-compose.neo4j.yml`
   - 启动 Neo4j 5.15 Community 版本
   - 端口: 7474 (HTTP), 7687 (Bolt)
   - 默认密码: `swe-agent-local`
   - 启用 APOC 插件

2. **DevContainer 集成**: 更新 `.devcontainer/devcontainer.json`
   - 添加 `dockerComposeFile` 指向 docker-compose.neo4j.yml
   - 更新环境变量: `NEO4J_URI=bolt://localhost:7687`
   - 添加 Neo4j 连接验证到 postcreate.sh

3. **等待 Neo4j 就绪**: `.devcontainer/postcreate.sh`
   - 最多等待 60 秒直到 Neo4j 启动
   - Python 验证连接是否成功

**修改文件:**
- `.devcontainer/docker-compose.neo4j.yml` - 新建
- `.devcontainer/devcontainer.json` - 添加 Docker Compose 和环境变量
- `.devcontainer/postcreate.sh` - 添加 Neo4j 等待和验证逻辑

---

## 5. ✅ 更新 harmony_graph 使用本地数据库

**修改:**
- `tools/harmony_graph/lib/core.py` 中的 `GlobalConfig` 类
- 默认连接字符串: `neo4j+s://外部数据库` → `bolt://localhost:7687`
- 默认密码: `外部密码` → `swe-agent-local`
- 保留环境变量覆盖能力(可通过 NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD 修改)

**修改文件:**
- `tools/harmony_graph/lib/core.py` - 更新 GlobalConfig 默认值

---

## 6. ✅ 扩展 harmony_graph 添加本地索引功能

**新增功能:**
`tools/harmony_graph/bin/code_indexer` - 代码索引器工具

**用法:**
```bash
# 索引当前目录
code_indexer

# 索引指定仓库
code_indexer /path/to/repo

# 强制重建索引
code_indexer /path/to/repo --force-clean

# 验证 Neo4j 连接
code_indexer --verify
```

**功能:**
- 扫描 C/C++ 源代码(`.c`, `.cpp`, `.h`, `.hpp`)
- 提取函数、类、结构体、include 依赖
- 分析 git 历史和提交信息
- 建立调用关系图
- 存储到本地 Neo4j 数据库

**修改文件:**
- `tools/harmony_graph/bin/code_indexer` - 已存在，验证可用
- `tools/harmony_graph/config.yaml` - 添加 code_indexer 工具文档

---

## 使用流程

### 1. 重建 DevContainer
```bash
# 在 VS Code 中执行:
Ctrl+Shift+P → "Dev Containers: Rebuild Container"
```

### 2. 验证 Neo4j 连接
```bash
code_indexer --verify
```

### 3. 索引仓库
```bash
# 索引目标仓库 (首次运行需要几分钟)
code_indexer /path/to/your/harmonyos/repo
```

### 4. 使用其他 harmony_graph 工具
```bash
# 查看文件依赖
inspect_file_topology src/foundation/ace/adapter.cpp

# 查找函数签名
verify_func_signature GetMessage

# 查找调用者
find_upstream_callers ValidateFields

# 查看文件历史
view_file_changelog src/google/protobuf/map_field.cc
```

### 5. 运行 Harmony MAS
```bash
python tools/run_harmony_mas.py \
  --repo_path /path/to/repo \
  --issue "修复告警描述"
```

---

## 关键改进

### Contract Agent 过度迭代问题

**问题:** contract_agent 执行了 490 次工具调用，远超预期的 8-10 次

**建议修复 (未在本次应用):**
```yaml
# config/agents/contract_agent.yaml
execution_timeout: 60  # 缩短到 60 秒
model:
  name: gpt-4o  # 升级到 gpt-4o
  per_instance_cost_limit: 1.0  # 降低成本限制强制提前停止
max_requeries: 1  # 减少重试次数
```

同时简化 contract_agent 的 system_template (类似 review_agent 的简化方式)

---

## 注意事项

1. **首次运行:** Neo4j 初始化需要约 20-30 秒
2. **索引时间:** 大型仓库(10k+ 文件)可能需要 5-10 分钟
3. **增量索引:** 再次运行 `code_indexer` 时只索引新文件(除非使用 --force-clean)
4. **静态分析:** Review Agent 会尝试使用 cppcheck，如果不可用会返回 CHECK_SKIPPED
5. **环境变量:** 可通过设置 NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD 覆盖默认配置

---

## 故障排查

### Neo4j 连接失败
```bash
# 检查 Neo4j 是否运行
curl http://localhost:7474

# 查看 Neo4j 日志
docker logs <neo4j_container_id>

# 手动重启 Neo4j
docker restart <neo4j_container_id>
```

### 索引失败
```bash
# 检查 tree-sitter 库是否存在
ls -la tools/harmony_graph/lib/libtree-sitter-cpp.so

# 安装依赖
pip install neo4j tree-sitter
```

### Review Agent 仍然无法正常工作
- 检查 gpt-4o 模型访问权限
- 查看轨迹文件中的具体错误
- 考虑进一步简化 prompt 或增加 execution_timeout
