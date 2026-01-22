# Harmony MAS + Defects4C 完整集成指南

## 概述

本指南提供了 Harmony Multi-Agent System 与 Defects4C benchmark 的完整集成方案。所有工具已经实现并可以直接使用。

## 关键问题解答

### Q1: Defects4C 是否提供 bug 信息？

**是的！** Defects4C 通过 API 提供完整的 bug 信息：

```python
# API 返回的数据包括：
{
  "status": "success",
  "bug_id": "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082",
  "prompt_data": {
    "temperature": 0.01,
    "prompt": [
      {
        "role": "system",
        "content": "You are a C/CPP code program repair expert"
      },
      {
        "role": "user",
        "content": "The following code contains a buggy hunk..."
      }
    ]
  },
  "type": {
    "name": "Logic Organization: Improper Condition Organization",
    "id": "D.1"
  }
}
```

### Q2: 如何获取仓库和 issue 信息？

**完全自动化！** 集成脚本会：

1. **从 bug_id 解析仓库信息**：
   - Bug ID 格式：`owner___repo@commit_sha`
   - 例如：`danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082`
   - 自动解析为：`https://github.com/danmar/cppcheck`

2. **自动克隆仓库**：
   ```python
   github_url = f"https://github.com/{owner}/{repo}.git"
   subprocess.run(["git", "clone", github_url, repo_dir])
   subprocess.run(["git", "checkout", commit_sha], cwd=repo_dir)
   ```

3. **从 API 数据构造 issue**：
   - 提取 buggy code
   - 提取 bug 类型
   - 构造符合 Harmony MAS 格式的 issue 描述

### Q3: 与 Harmony MAS 的集成方式？

**直接调用！** 脚本直接导入并调用 HarmonyCoordinator：

```python
from sweagent.agent.mas.harmony_coordinator import HarmonyCoordinator

coordinator = HarmonyCoordinator(
    env=env,
    topology_config=topology_config,
    temporal_config=temporal_config,
    patch_generator_config=patch_generator_config,
    verification_config=verification_config,
    output_dir=output_dir,
    max_iterations=3,
    num_candidate_patches=3,
)

result = coordinator.run(problem_statement=problem_statement)
```

## 已创建的工具

### 1. 完整集成脚本（核心）

**文件：** `tools/run_defects4c_test.py`

这是完整的端到端集成脚本，包含：

- ✅ 从 Defects4C API 获取 bug 信息
- ✅ 自动克隆 GitHub 仓库
- ✅ 自动切换到 buggy commit
- ✅ 构造 issue 描述
- ✅ 调用 Harmony MAS 生成修复
- ✅ 提取生成的 patch
- ✅ 提交到 Defects4C 验证
- ✅ 保存完整结果

**特点：**
- 完全自动化，无需手动操作
- 支持所有 Defects4C 项目
- 详细的日志输出
- 结构化的结果保存

### 2. 批量测试脚本

**文件：** `tools/batch_test_defects4c.sh`

批量测试多个 bugs：
- 自动循环测试
- 生成统计报告
- 保存所有日志

### 3. Bug 浏览工具

**文件：** `tools/list_defects4c_bugs.py`

浏览和选择测试用例

### 4. 快速启动脚本

**文件：** `tools/defects4c_quickstart.sh`

快速测试 API 连接

## 使用方法

### 方法 1：测试单个 Bug（推荐开始）

```bash
# 测试一个简单的 bug
python tools/run_defects4c_test.py \
    --bug_id "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082" \
    --work_dir "work/defects4c_test1" \
    --max_iterations 3 \
    --num_candidate_patches 3
```

**执行流程：**
1. 从 Defects4C API 获取 bug 信息
2. 克隆 `https://github.com/danmar/cppcheck` 到 `work/defects4c_test1/repos/`
3. 切换到 commit `099b4435c38dd52ddb38e6b1706d9c988699c082`
4. 构造 issue 描述
5. 运行 Harmony MAS（最多 3 次迭代，每次生成 3 个候选 patch）
6. 提取最佳 patch
7. 提交到 Defects4C 验证
8. 保存结果到 `work/defects4c_test1/results/`

**预期输出：**
```
==================================================
STAGE 1: FETCH BUG INFORMATION
==================================================
✅ Successfully fetched bug info

==================================================
STAGE 2: CLONE REPOSITORY
==================================================
✅ Repository cloned to work/defects4c_test1/repos/danmar___cppcheck
✅ Checked out commit 099b4435c38dd52ddb38e6b1706d9c988699c082

==================================================
STAGE 3: CONSTRUCT ISSUE DESCRIPTION
==================================================
Constructed issue description (1234 chars)

==================================================
STAGE 4: RUN HARMONY MAS
==================================================
[Harmony MAS 执行过程...]

==================================================
STAGE 5: EXTRACT PATCH
==================================================
✅ Extracted patch (567 chars)

==================================================
STAGE 6: SUBMIT TO DEFECTS4C
==================================================
✅ Patch built: /patches/xxx.patch
✅ Verification submitted, handle: abc123
Verification status: running
Verification status: completed
✅ Verification PASSED!

==================================================
TEST SUMMARY
==================================================
Bug ID: danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082
Overall Success: True
✅ TEST PASSED - Bug successfully fixed!
```

### 方法 2：批量测试

```bash
# 编辑 tools/batch_test_defects4c.sh 添加更多 bugs
# 然后运行：
bash tools/batch_test_defects4c.sh
```

**批量测试会：**
- 测试所有配置的 bugs
- 生成统计报告
- 保存所有日志和结果

### 方法 3：选择测试用例

```bash
# 1. 浏览可用的 bugs
python tools/list_defects4c_bugs.py --project danmar___cppcheck --limit 10

# 2. 选择一个 bug ID
# 3. 运行测试
python tools/run_defects4c_test.py --bug_id "<选择的bug_id>"
```

## 推荐的测试流程

### 第一步：快速验证（5 分钟）

```bash
# 1. 测试 API 连接
bash tools/defects4c_quickstart.sh

# 2. 浏览可用的 bugs
python tools/list_defects4c_bugs.py --project danmar___cppcheck --simple
```

### 第二步：单个 Bug 测试（30-60 分钟）

```bash
# 测试一个简单的 bug
python tools/run_defects4c_test.py \
    --bug_id "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082"
```

**注意事项：**
- 首次运行会下载 Docker 镜像（如果没有）
- 克隆仓库需要网络连接
- Harmony MAS 执行时间取决于 bug 复杂度（通常 10-30 分钟）
- Defects4C 验证需要 1-5 分钟

### 第三步：批量测试（几小时）

```bash
# 编辑 batch_test_defects4c.sh，添加更多 bugs
# 然后运行批量测试
bash tools/batch_test_defects4c.sh
```

## 参数说明

### run_defects4c_test.py 参数

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--bug_id` | ✅ | - | Bug ID（格式：`project@commit_sha`） |
| `--work_dir` | ❌ | `work/defects4c` | 工作目录 |
| `--coordinator_config` | ❌ | `config/agents/coordinator_agent.yaml` | Coordinator 配置文件 |
| `--max_iterations` | ❌ | 3 | 最大迭代次数 |
| `--num_candidate_patches` | ❌ | 3 | 每次迭代生成的候选 patch 数量 |
| `--docker_image` | ❌ | `python:3.11` | Docker 镜像 |

## 结果文件

### 结果目录结构

```
work/defects4c_test1/
├── repos/                          # 克隆的仓库
│   └── danmar___cppcheck/
├── results/                        # 测试结果
│   ├── danmar___cppcheck@099b...json  # 详细结果
│   └── harmony_output/             # Harmony MAS 输出
└── logs/                           # 日志文件（批量测试）
```

### 结果 JSON 格式

```json
{
  "bug_id": "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082",
  "timestamp": "2024-01-21T10:30:00",
  "overall_success": true,
  "stages": {
    "fetch_bug_info": {
      "success": true,
      "data": { ... }
    },
    "clone_repository": {
      "success": true,
      "repo_path": "/path/to/repo"
    },
    "construct_issue": {
      "success": true,
      "issue": "Bug Fix Request..."
    },
    "run_harmony_mas": {
      "success": true
    },
    "extract_patch": {
      "success": true,
      "patch_length": 567
    },
    "verification": {
      "success": true,
      "fix_status": "success",
      "details": { ... }
    }
  }
}
```

## 推荐的测试用例

### 简单（适合首次测试）

```bash
# 1. Logic Organization bug
python tools/run_defects4c_test.py \
    --bug_id "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082"

# 2. Control Expression Error
python tools/run_defects4c_test.py \
    --bug_id "danmar___cppcheck@caa6ff7c2a6ef64df53e04701944aaa4712a1915"
```

### 中等难度

```bash
# Null Pointer Dereference
python tools/run_defects4c_test.py \
    --bug_id "danmar___cppcheck@4996ec190ecf27a4bf018eb0dcd12e2a51fd550e"
```

### 查找更多测试用例

```bash
# 查看所有项目
python tools/list_defects4c_bugs.py

# 查看特定项目的简单 bugs
python tools/list_defects4c_bugs.py --project danmar___cppcheck --simple

# 查看特定类别的 bugs
python tools/list_defects4c_bugs.py --project danmar___cppcheck --category "B"
```

## 故障排除

### 问题 1：API 连接失败

```bash
# 测试 API 连接
python -c "import requests; print(requests.get('https://defects4c.wj2ai.com/list_defects_bugid').status_code)"
```

### 问题 2：仓库克隆失败

- 检查网络连接
- 确保有足够的磁盘空间
- 某些仓库可能需要完整克隆（脚本会自动重试）

### 问题 3：Harmony MAS 失败

- 检查 Docker 是否运行
- 检查 Neo4j 是否可访问
- 查看详细日志：`work/defects4c_test1/results/harmony_output/`

### 问题 4：验证超时

- Defects4C 验证可能需要几分钟
- 默认超时 5 分钟
- 可以在代码中调整 `max_wait` 参数

## 评估指标

### 成功标准

- ✅ `overall_success == true`
- ✅ `verification.fix_status == "success"`
- ✅ 所有单元测试通过

### 统计指标

批量测试会生成：
- **Pass@1**: 第一次尝试成功率
- **总成功率**: 所有测试的成功率
- **平均执行时间**: 每个 bug 的平均时间

## 下一步

### 立即开始

```bash
# 1. 快速验证
bash tools/defects4c_quickstart.sh

# 2. 测试第一个 bug
python tools/run_defects4c_test.py \
    --bug_id "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082"

# 3. 查看结果
cat work/defects4c/results/*_result.json | jq '.overall_success'
```

### 扩展测试

1. 添加更多 bugs 到 `batch_test_defects4c.sh`
2. 调整 Harmony MAS 参数（迭代次数、候选数量）
3. 测试不同项目（fmt, CLI11, etc.）
4. 分析失败案例，改进系统

### 性能优化

- 使用本地 Git 缓存避免重复克隆
- 并行运行多个测试（需要修改脚本）
- 使用更快的 Docker 镜像

## 技术细节

### 工作流程图

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Fetch Bug Info from Defects4C API                       │
│    - Bug type, commit SHA, buggy code                       │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│ 2. Clone Repository                                         │
│    - Parse owner/repo from bug_id                           │
│    - Clone from GitHub                                      │
│    - Checkout buggy commit                                  │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│ 3. Construct Issue Description                              │
│    - Extract buggy code from API response                   │
│    - Format for Harmony MAS                                 │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│ 4. Run Harmony MAS                                          │
│    - Create SWE environment                                 │
│    - Load agent configurations                              │
│    - Run HarmonyCoordinator                                 │
│    - Generate and verify patches                            │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│ 5. Extract Patch                                            │
│    - Get final_patch from shared_state                      │
│    - Extract patch_content                                  │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│ 6. Submit to Defects4C                                      │
│    - Build patch via API                                    │
│    - Submit for verification                                │
│    - Poll for results                                       │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│ 7. Save Results                                             │
│    - Save detailed JSON                                     │
│    - Generate summary                                       │
└─────────────────────────────────────────────────────────────┘
```

### 关键代码片段

**自动克隆仓库：**
```python
github_url = f"https://github.com/{owner}/{repo}.git"
subprocess.run(["git", "clone", github_url, repo_dir])
subprocess.run(["git", "checkout", commit_sha], cwd=repo_dir)
```

**调用 Harmony MAS：**
```python
coordinator = HarmonyCoordinator(
    env=env,
    topology_config=topology_config,
    temporal_config=temporal_config,
    patch_generator_config=patch_generator_config,
    verification_config=verification_config,
    output_dir=output_dir,
    max_iterations=max_iterations,
    num_candidate_patches=num_candidate_patches,
)
result = coordinator.run(problem_statement=problem_statement)
```

**提取 patch：**
```python
shared_state = harmony_result.get("shared_state")
final_patch = shared_state.final_patch
patch_content = final_patch.patch_content
```

## 总结

✅ **完全自动化**：从 bug_id 到验证结果，无需手动操作

✅ **真实集成**：直接调用 Harmony MAS，不是 mock

✅ **完整流程**：包含克隆、修复、验证的完整流程

✅ **易于使用**：一条命令即可开始测试

✅ **可扩展**：支持批量测试和自定义配置

现在你可以立即开始测试你的 Harmony MAS 系统在 Defects4C benchmark 上的表现！
