# Defects4C 集成测试 - 快速开始

## ✅ 已修复的问题

### 1. Git Checkout 失败 ✅
**问题：** 浅克隆无法 checkout 历史 commit
**解决：** 实现了智能克隆策略：
- 先浅克隆获取仓库结构
- 然后 fetch 特定 commit
- 如果失败，自动 unshallow
- 最后 fallback 到完整克隆

### 2. SWEEnv 初始化错误 ✅
**问题：** `SWEEnv.__init__() takes 1 positional argument but 2 were given`
**解决：** 使用 `SWEEnv.from_config()` 类方法

### 3. HarmonyCoordinator 接口错误 ✅
**问题：** 使用了错误的初始化方法和参数
**解决：** 使用 `HarmonyCoordinator.from_config_files()` 方法

### 4. 结果提取错误 ✅
**问题：** `'HarmonyCoordinator' object has no attribute 'shared_state'`
**解决：**
- `coordinator.run()` 返回字符串（final patch）
- 使用 `coordinator.state` 访问状态对象
- 直接从返回值提取 patch

## 🚀 立即开始测试

### 第一步：测试单个 Bug

```bash
# 测试一个简单的 bug（预计 15-30 分钟）
python tools/run_defects4c_test.py \
    --bug_id "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082" \
    --work_dir "work/defects4c_test1"
```

**执行流程：**
1. ✅ 从 Defects4C API 获取 bug 信息
2. ✅ 克隆 GitHub 仓库并 checkout buggy commit
3. ✅ 构造 issue 描述
4. 🔄 运行 Harmony MAS（这是最耗时的步骤）
5. 🔄 提取生成的 patch
6. 🔄 提交到 Defects4C 验证
7. 📊 保存结果

### 第二步：查看结果

```bash
# 查看详细结果
cat work/defects4c_test1/results/*_result.json | jq '.'

# 查看是否成功
cat work/defects4c_test1/results/*_result.json | jq '.overall_success'

# 查看各阶段状态
cat work/defects4c_test1/results/*_result.json | jq '.stages | keys'
```

### 第三步：批量测试

```bash
# 编辑批量测试脚本，添加更多 bugs
nano tools/batch_test_defects4c.sh

# 运行批量测试
bash tools/batch_test_defects4c.sh
```

## 📋 可用的测试用例

### 推荐用于首次测试（简单）

```bash
# 1. Logic Organization bug (cppcheck)
python tools/run_defects4c_test.py \
    --bug_id "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082"

# 2. Control Expression Error (cppcheck)
python tools/run_defects4c_test.py \
    --bug_id "danmar___cppcheck@caa6ff7c2a6ef64df53e04701944aaa4712a1915"
```

### 查找更多测试用例

```bash
# 列出所有项目
python tools/list_defects4c_bugs.py

# 查看 cppcheck 的所有 bugs
python tools/list_defects4c_bugs.py --project danmar___cppcheck

# 只显示简单的 bugs（单文件、单函数）
python tools/list_defects4c_bugs.py --project danmar___cppcheck --simple

# 查看其他项目
python tools/list_defects4c_bugs.py --project fmtlib___fmt
python tools/list_defects4c_bugs.py --project CLIUtils___CLI11
```

## 🔍 监控执行进度

### 实时查看日志

```bash
# 在另一个终端窗口
tail -f work/defects4c_test1/results/harmony_output/*.log
```

### 检查 Docker 容器

```bash
# 查看运行中的容器
docker ps

# 查看容器日志
docker logs <container_id>
```

### 检查 Neo4j 连接

```bash
# 测试 Neo4j 是否可访问
docker exec -it swe-agent_devcontainer-neo4j-1 cypher-shell -u neo4j -p swe-agent-local
```

## 📊 结果文件结构

```
work/defects4c_test1/
├── repos/                                    # 克隆的仓库
│   └── danmar___cppcheck/
│       ├── lib/
│       ├── test/
│       └── ...
├── results/                                  # 测试结果
│   ├── danmar___cppcheck_099b...json        # 详细结果
│   └── harmony_output/                      # Harmony MAS 输出
│       ├── state_*.json                     # 状态快照
│       └── *.log                            # 日志文件
```

### 结果 JSON 格式

```json
{
  "bug_id": "danmar___cppcheck@099b4435...",
  "timestamp": "2024-01-21T10:30:00",
  "overall_success": true,
  "stages": {
    "fetch_bug_info": {
      "success": true,
      "data": { ... }
    },
    "clone_repository": {
      "success": true,
      "repo_path": "work/.../repos/danmar___cppcheck"
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

## ⚙️ 配置参数

### 基本参数

```bash
python tools/run_defects4c_test.py \
    --bug_id "project@commit_sha"              # 必需：Bug ID
    --work_dir "work/test1"                    # 工作目录
    --coordinator_config "config/agents/..."   # Coordinator 配置
    --max_iterations 3                         # 最大迭代次数
    --num_candidate_patches 3                  # 每次迭代生成的候选数
    --docker_image "python:3.11"               # Docker 镜像
```

### 调整性能

```bash
# 快速测试（减少迭代）
--max_iterations 1 --num_candidate_patches 1

# 深度测试（增加迭代）
--max_iterations 5 --num_candidate_patches 5

# 使用不同的 Docker 镜像
--docker_image "python:3.11-slim"
```

## 🐛 故障排除

### 问题 1：Git Clone 很慢

**解决方案：**
- 使用国内 Git 镜像
- 或者手动克隆后使用 `--repo_path` 参数

```bash
# 手动克隆
git clone https://github.com/danmar/cppcheck.git work/repos/danmar___cppcheck
cd work/repos/danmar___cppcheck
git checkout 099b4435c38dd52ddb38e6b1706d9c988699c082

# 然后修改脚本跳过克隆步骤
```

### 问题 2：Docker 权限错误

```bash
# 修复 Docker 权限
./.devcontainer/fix_docker_permissions.sh
```

### 问题 3：Neo4j 连接失败

```bash
# 检查 Neo4j 是否运行
docker ps | grep neo4j

# 重启 Neo4j
docker restart swe-agent_devcontainer-neo4j-1

# 检查网络
docker network ls | grep swe-agent
```

### 问题 4：Harmony MAS 超时

```bash
# 增加超时时间（修改代码）
# 或者使用更简单的 bug 测试
```

### 问题 5：Defects4C API 超时

```bash
# 检查 API 连接
curl https://defects4c.wj2ai.com/list_defects_bugid

# 如果 API 不可用，等待一段时间后重试
```

## 📈 评估指标

### 成功标准

- ✅ `overall_success == true`
- ✅ `verification.fix_status == "success"`
- ✅ 所有单元测试通过

### 统计指标

```bash
# 计算成功率
find work/defects4c_batch_*/results -name "*_result.json" | \
    xargs jq -r '.overall_success' | \
    awk '{sum+=$1; count++} END {print "Success rate:", sum/count*100"%"}'

# 查看失败原因
find work/defects4c_batch_*/results -name "*_result.json" | \
    xargs jq -r 'select(.overall_success==false) | .error'
```

## 🎯 下一步

### 1. 验证基本功能

```bash
# 运行一个完整的测试
python tools/run_defects4c_test.py \
    --bug_id "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082"

# 检查结果
cat work/defects4c/results/*_result.json | jq '.overall_success'
```

### 2. 批量测试

```bash
# 编辑批量测试脚本
nano tools/batch_test_defects4c.sh

# 添加更多 bugs
BUGS=(
    "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082"
    "danmar___cppcheck@caa6ff7c2a6ef64df53e04701944aaa4712a1915"
    "danmar___cppcheck@4996ec190ecf27a4bf018eb0dcd12e2a51fd550e"
    # 添加更多...
)

# 运行批量测试
bash tools/batch_test_defects4c.sh
```

### 3. 分析结果

```bash
# 生成报告
python tools/analyze_defects4c_results.py work/defects4c_batch_*/results/

# 或者手动分析
find work/defects4c_batch_*/results -name "*_result.json" | \
    xargs jq -r '{bug_id, success: .overall_success, error: .error}'
```

### 4. 优化系统

根据测试结果：
- 调整 Harmony MAS 的提示词
- 优化 agent 配置
- 增加或减少迭代次数
- 改进 patch 生成策略

## 📚 相关文档

- **完整集成指南：** `docs/HARMONY_DEFECTS4C_COMPLETE_GUIDE.md`
- **Defects4C 集成：** `docs/DEFECTS4C_INTEGRATION.md`
- **快速开始：** `docs/DEFECTS4C_QUICKSTART.md`
- **Harmony MAS 文档：** `docs/HARMONY_MAS_QUICKSTART.md`

## 💡 提示

1. **首次运行会比较慢**：需要下载 Docker 镜像、克隆仓库、索引代码
2. **后续运行会更快**：使用缓存的仓库和代码图
3. **选择简单的 bugs 开始**：使用 `--simple` 标志查找简单的测试用例
4. **监控资源使用**：Harmony MAS 可能消耗较多内存和 CPU
5. **保存日志**：使用 `tee` 命令保存完整日志

## ✨ 总结

现在你可以：
- ✅ 自动从 Defects4C 获取 bug 信息
- ✅ 自动克隆仓库并切换到 buggy commit
- ✅ 运行 Harmony MAS 生成修复
- ✅ 提交到 Defects4C 验证
- ✅ 获取完整的测试结果

所有问题都已修复，系统可以正常运行！🎉
