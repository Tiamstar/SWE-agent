# PR Base Commit 提取工具使用说明

## 功能说明

这个工具帮助你获取每个 PR 提交**之前**的仓库状态，即 PR 进行 diff 对比时的基准版本。

## 核心原理

对于每个 PR，脚本会：
1. 克隆仓库
2. 获取 PR 分支
3. 使用 `git merge-base` 找到 PR 分支与目标分支的**共同祖先提交**（这就是 PR 修改前的版本）
4. 在该提交处创建一个新分支供你使用

## 使用方法

### 方法 1: 直接运行主脚本

```bash
python3 get_pr_base_commits.py
```

这会处理脚本中预设的所有 PR 链接，并在 `pr_base_repos/` 目录下创建对应的仓库。

### 方法 2: 手动处理单个 PR

如果你想手动处理某个 PR，可以使用以下命令：

```bash
# 1. 克隆仓库
git clone https://gitcode.com/openharmony/distributeddatamgr_relational_store.git

# 2. 进入仓库
cd distributeddatamgr_relational_store

# 3. 获取 PR 分支（PR #2983）
git fetch origin pull/2983/head:pr-2983

# 4. 找到基准提交（merge base）
BASE_COMMIT=$(git merge-base pr-2983 origin/master)
echo "Base commit: $BASE_COMMIT"

# 5. 创建并切换到基准分支
git checkout -b base-before-pr2983 $BASE_COMMIT

# 6. 查看 PR 的改动
git diff $BASE_COMMIT pr-2983
```

## 输出结果

脚本运行后会生成：

### 1. 仓库目录结构
```
pr_base_repos/
├── distributeddatamgr_relational_store_PR2983/
├── distributeddatamgr_relational_store_PR3002/
├── communication_netstack_PR2205/
├── arkui_ace_engine_PR79534/
└── distributedhardware_distributed_hardware_fwk_PR1163/
```

每个目录都是完整的 git 仓库，已经切换到 PR 修改前的提交。

### 2. JSON 结果文件 (`pr_base_commits.json`)
```json
[
  {
    "pr_url": "https://gitcode.com/openharmony/...",
    "repo_name": "distributeddatamgr_relational_store",
    "pr_number": "2983",
    "base_commit": "abc123...",
    "base_commit_message": "...",
    "local_path": "/path/to/pr_base_repos/...",
    "base_branch_name": "base-before-pr2983"
  }
]
```

### 3. Markdown 摘要 (`SUMMARY.md`)
包含每个 PR 的详细信息和使用命令。

## 使用提取的仓库

### 查看修复前的代码
```bash
cd pr_base_repos/distributeddatamgr_relational_store_PR2983
# 当前已经在 base-before-pr2983 分支，这就是修复前的代码
```

### 查看 PR 做了什么修改
```bash
cd pr_base_repos/distributeddatamgr_relational_store_PR2983
git diff base-before-pr2983 pr-2983
```

### 查看修改的文件列表
```bash
git diff --name-only base-before-pr2983 pr-2983
```

### 查看具体某个文件的修改
```bash
git diff base-before-pr2983 pr-2983 -- path/to/file.cpp
```

## 故障排除

### 问题 1: GitCode 的 PR 引用格式不同

如果脚本无法获取 PR，GitCode 可能使用不同的引用格式。尝试：

```bash
cd repo_directory
# 查看所有远程引用
git ls-remote origin | grep pull
# 或
git ls-remote origin | grep merge
```

然后根据输出调整脚本中的引用格式。

### 问题 2: 需要认证

如果仓库是私有的，你需要配置 Git 认证：

```bash
# 方法 1: 使用 credential helper
git config --global credential.helper store

# 方法 2: 在 URL 中包含 token
git clone https://username:token@gitcode.com/org/repo.git
```

### 问题 3: 默认分支不是 master

脚本会自动检测默认分支，但如果失败，你可以手动指定：

```bash
git merge-base pr-2983 origin/main  # 如果默认分支是 main
```

## 高级用法

### 批量导出 PR 的 patch 文件

```bash
for dir in pr_base_repos/*/; do
    cd "$dir"
    repo_name=$(basename "$dir")
    pr_num=$(echo "$repo_name" | grep -oP 'PR\K\d+')
    git diff base-before-pr${pr_num} pr-${pr_num} > "../${repo_name}.patch"
    cd ..
done
```

### 在修复前的代码上运行测试

```bash
cd pr_base_repos/distributeddatamgr_relational_store_PR2983
# 当前在修复前的版本
make test  # 或其他测试命令
```

### 应用 PR 的修改到新分支

```bash
cd pr_base_repos/distributeddatamgr_relational_store_PR2983
git checkout -b my-fix base-before-pr2983
git cherry-pick pr-2983  # 应用 PR 的修改
```

## 与 SWE-agent 集成

如果你想用 SWE-agent 来修复这些问题：

```bash
# 使用提取的仓库作为本地仓库
sweagent run \
    --config config/default.yaml \
    --agent.model.name "gpt-4o" \
    --env.repo.path /path/to/pr_base_repos/distributeddatamgr_relational_store_PR2983 \
    --problem_statement.path problem_statement.md
```

## 脚本参数说明

你可以修改脚本中的参数：

```python
# 修改输出目录
extractor = PRBaseExtractor(output_dir="my_custom_dir")

# 添加更多 PR URL
pr_urls = [
    "https://gitcode.com/org/repo/pull/123",
    # ... 更多 URL
]
```

## 注意事项

1. **网络要求**: 需要能访问 gitcode.com
2. **磁盘空间**: 每个仓库可能需要几百 MB 到几 GB
3. **Git 版本**: 建议使用 Git 2.20+
4. **时间**: 首次克隆可能需要较长时间

## 相关命令速查

```bash
# 查看当前分支
git branch

# 查看当前提交
git log -1

# 切换到 PR 分支查看修复后的代码
git checkout pr-2983

# 切换回修复前的代码
git checkout base-before-pr2983

# 查看所有分支
git branch -a

# 查看提交历史
git log --oneline --graph --all
```
