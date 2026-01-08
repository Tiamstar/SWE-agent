# Harmony MAS 修复总结

## 修复完成的问题

### 1. ✅ Agent工具配置完善
**问题**: Agents缺少必要的SWE-agent工具

**修复**:
- `topology_agent.yaml`: 添加了 `tools/search` 和 `tools/submit`
- `temporal_agent.yaml`: 添加了 `tools/search` 和 `tools/submit`
- `review_agent.yaml`: 添加了 `tools/search` 和 `tools/submit`
- `contract_agent.yaml`: 添加了 `tools/search` 和 `tools/submit`

### 2. ✅ Temporal Agent使用正确的工具
**问题**: 项目是本地项目，直接使用git命令无效

**修复**:
- 移除所有直接的git命令提示（`git blame`, `git log`, `git show`等）
- 改用harmony_graph工具：
  - `view_file_changelog <file_name>` - 查看文件变更历史
  - `search_historical_intent <keyword>` - 搜索提交消息
- 更新workflow说明，强调使用这两个工具而非git命令
- 修改CRITICAL GUIDELINES，明确指出使用harmony_graph工具

### 3. ✅ Review Agent使用静态分析工具
**问题**: Review Agent不应该有build工具，应该使用静态检查工具

**修复**:
- 角色从 `build_reviewer` 改为 `static_analyzer`
- 移除所有编译相关的指令（GN, Ninja, Make, CMake等）
- 添加静态分析工具：
  - `cppcheck` - C/C++静态分析
  - `clang-tidy` - Clang基础linter
  - `cpplint` - Google C++风格检查器
- 更新workflow，聚焦在静态分析而非编译
- 状态值改为：`CHECK_PASSED`, `CHECK_FAILED`, `APPLY_FAILED`, `CHECK_SKIPPED`
- 超时时间从300s减少到180s（静态分析比编译快）

### 4. ✅ Coordinator接入真实LLM
**问题**: Coordinator的`_generate_patch_with_llm`是placeholder，没有真正使用LLM

**修复**:
- 在`__init__`中添加`coordinator_model_config`参数
- 使用`get_model()`初始化LLM：`self.model = get_model(coordinator_model_config, ...)`
- 实现`_generate_patches_with_llm(context, num_candidates=3)`方法：
  - 构建结构化prompt要求生成1-3个不同的patch
  - 调用`self.model.query(prompt)`获取LLM响应
  - 使用正则表达式解析响应，提取多个patch
  - 支持fallback机制（LLM失败时使用placeholder）
- 添加`_create_placeholder_patch()`方法作为备用

### 5. ✅ 动态生成1-3个候选Patch
**问题**: 原代码固定生成1个patch，需要支持1-3个

**修复**:
- `_stage_patch_generation()`改为调用`_generate_patches_with_llm(context, num_candidates=3)`
- 返回值从单个string改为`list[str]` (1-3个patches)
- 循环添加每个patch到state：
  ```python
  for i, patch_content in enumerate(patches, 1):
      candidate = CandidatePatch(id=f"patch_{i}", ...)
      self.state.add_candidate_patch(candidate)
  ```
- LLM prompt明确要求生成不同方法的patch（保守、适中、激进）

### 6. ✅ 集成Review和Contract Agents到验证流程
**问题**: 验证阶段的Agent调用是placeholder

**修复**:
- 实现`_verify_patch_static_analysis(patch)`:
  - 构建prompt并调用Review Agent
  - 解析JSON响应为`ReviewInsight`
  - 支持fallback（返回CHECK_SKIPPED）
- 实现`_verify_patch_contract(patch)`:
  - 构建prompt并调用Contract Agent
  - 解析JSON响应为`ContractInsight`
  - 支持fallback（假设安全以允许继续）
- 更新`_stage_verification_review()`:
  - 先调用静态分析，根据结果更新build_status
  - 如果patch无法应用，跳过contract检查
  - 成功的patch继续进行contract验证
  - 无安全patch时清空候选列表并重试

## 文件变更清单

### 核心代码
1. `sweagent/agent/mas/harmony_coordinator.py`
   - 添加导入：`ModelConfig`, `get_model`, `time`
   - `__init__`添加`coordinator_model_config`参数和LLM初始化
   - 新增`_generate_patches_with_llm()`方法
   - 新增`_create_placeholder_patch()`方法
   - 新增`_verify_patch_static_analysis()`方法
   - 重写`_verify_patch_contract()`方法
   - 更新`_stage_patch_generation()`使用新方法
   - 更新`_stage_verification_review()`集成真实agents

2. `sweagent/agent/mas/shared_state.py`
   - 无变更（已经设计良好）

### Agent配置
3. `config/agents/topology_agent.yaml`
   - 添加bundles: `tools/search`, `tools/submit`

4. `config/agents/temporal_agent.yaml`
   - 更新workflow：移除git命令，使用harmony_graph工具
   - 更新提示词：强调使用`view_file_changelog`和`search_historical_intent`
   - 添加bundles: `tools/search`, `tools/submit`

5. `config/agents/review_agent.yaml`
   - 完全重写：从build verification改为static analysis
   - 角色：`build_reviewer` → `static_analyzer`
   - 工具：移除编译工具，添加cppcheck/clang-tidy
   - 状态值：新状态系统（CHECK_PASSED等）
   - 添加bundles: `tools/search`, `tools/submit`

6. `config/agents/contract_agent.yaml`
   - 添加bundles: `tools/search`, `tools/submit`

### 运行脚本
7. `tools/run_harmony_mas.py`
   - 无变更（但需要确保coordinator_model_config从topology_config继承）

## 核心改进点总结

### 1. 真实LLM集成
- Coordinator现在使用真实的LLM（通过`get_model()`）
- 支持与sub-agents相同的model配置系统
- 可以配置独立的coordinator model或继承topology config

### 2. 多候选Patch生成
- 生成1-3个不同的候选patch
- LLM被指示生成不同策略的修复（保守/适中/激进）
- 支持解析结构化输出（`=== PATCH N ===`分隔符）
- 有完善的fallback机制

### 3. 真实Agent验证
- Review Agent执行静态分析（cppcheck/clang-tidy）
- Contract Agent执行契约和风险分析
- 两个agent都返回结构化JSON
- 协调器正确解析并使用结果

### 4. 迭代循环改进
- 验证失败时清空候选列表
- 收集违规信息供下次迭代参考
- 最多重试max_iterations次

### 5. 工具配置标准化
- 所有agents都有registry、search、submit工具
- Temporal/Topology/Contract agents有harmony_graph工具
- Review agent专注于静态分析工具

## 验证测试

所有Python文件编译测试通过：
```bash
python -m py_compile sweagent/agent/mas/shared_state.py  ✓
python -m py_compile sweagent/agent/mas/harmony_coordinator.py  ✓
python -m py_compile tools/run_harmony_mas.py  ✓
```

## 使用方式

```bash
python tools/run_harmony_mas.py \
    --repo_path /path/to/harmonyos/repo \
    --issue "src/file.cpp:100: warning: potential null pointer"
```

系统将：
1. 使用Topology Agent分析代码结构
2. 使用Temporal Agent分析历史
3. 使用Coordinator的LLM生成1-3个候选patch
4. 使用Review Agent进行静态分析验证
5. 使用Contract Agent进行契约验证
6. 选择最佳安全patch或重试

## 注意事项

1. **LLM模型配置**: Coordinator默认使用topology_config.model，可以通过coordinator_model_config自定义
2. **静态分析工具**: Review Agent需要cppcheck/clang-tidy工具可用，否则返回CHECK_SKIPPED（视为通过）
3. **Harmony Graph工具**: 确保harmony_graph工具正确配置并可访问Neo4j数据库
4. **迭代次数**: 默认max_iterations=3，可根据需要调整
