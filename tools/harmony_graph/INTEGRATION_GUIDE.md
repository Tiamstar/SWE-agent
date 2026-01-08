# Harmony Graph Tools - 集成说明

## 问题回答

### 1. Tools如何从all_local.py被改造以适应SWE-agent框架？

**原始设计 (all_local.py):**
- 单一文件包含所有功能（索引+查询）
- 需要tree-sitter进行AST解析
- 需要libtree-sitter-cpp.so编译库
- 适合独立使用，但不适合容器化环境

**改造方案:**

1. **模块化拆分** (`tools/harmony_graph/`):
   ```
   bin/
     ├── code_graph         # 核心CLI工具（查询功能）
     ├── code_indexer       # 索引工具（独立使用）
     └── [wrapper scripts]  # 9个工具wrapper
   lib/
     └── core.py           # 核心库（从all_local.py改造）
   ```

2. **依赖简化**:
   - 将`tree_sitter`导入从顶层移到`IndexerEngine`内部（lazy import）
   - 查询功能只需要`neo4j`库
   - 索引功能才需要`tree_sitter`（可选）

3. **接口适配**:
   - 创建9个wrapper scripts，每个对应config.yaml中定义的一个工具
   - wrapper通过bash调用`code_graph`主程序并传递子命令
   - 例如：`inspect_file_topology` → `code_graph dependencies`

4. **配置外部化**:
   - Neo4j连接通过环境变量配置（NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD）
   - 支持在容器启动时注入配置

### 2. 改造后的Tools是否真正能在环境中被解析并执行？

**答案：是的，已验证通过所有测试。**

**验证方法：**

```bash
# 运行集成测试
python tools/test_harmony_tools.py
```

**测试覆盖：**
1. ✓ 工具可执行性 - 所有11个工具都存在且可执行
2. ✓ Python导入 - core模块可以正常导入，无tree_sitter依赖
3. ✓ 工具执行 - wrapper scripts正确路由到code_graph，返回标准JSON

**执行流程：**

```
Agent调用工具
    ↓
inspect_file_topology main.cpp
    ↓
wrapper script (bash)
    ↓
code_graph dependencies main.cpp
    ↓
core.py → GraphQueryService.get_file_dependencies()
    ↓
Neo4j查询
    ↓
JSON结果返回给Agent
```

## 使用前提

**必需条件：**
1. Neo4j数据库已运行并可访问
2. 代码库已在Neo4j中索引（使用all_local.py或code_indexer）
3. 环境变量已设置：
   ```bash
   export NEO4J_URI="bolt://your-neo4j-host:7687"
   export NEO4J_USER="neo4j"
   export NEO4J_PASSWORD="your_password"
   ```

**在SWE-agent多Agent环境中：**
- 在`run_mas_simple.py`中通过`post_startup_commands`注入环境变量
- 工具会在容器初始化时自动安装（通过install.sh）
- 每次运行都是新容器，但连接的是同一个外部Neo4j数据库

## 测试示例

```bash
# 测试wrapper script
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="your_password"

# 查询文件依赖
./tools/harmony_graph/bin/inspect_file_topology main.cpp

# 查询函数签名
./tools/harmony_graph/bin/verify_func_signature InitializeApp

# 查询类结构
./tools/harmony_graph/bin/inspect_class_schema Application
```

## 架构优势

1. **轻量级**: 查询功能只需neo4j库，无需编译.so文件
2. **容器友好**: 依赖简单，安装快速
3. **外部化数据**: Neo4j运行在容器外，数据持久化
4. **标准接口**: 符合SWE-agent工具规范，返回JSON格式

## 下一步

如需在真实环境中使用：
1. 启动Neo4j数据库
2. 使用all_local.py索引目标代码库
3. 在run_mas_simple.py中配置Neo4j连接参数
4. 运行多Agent系统，工具会自动可用
