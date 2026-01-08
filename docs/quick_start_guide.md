# 快速使用指南

## 立即开始

### 使用本地仓库（支持未提交的修改）

```bash
# 对有未提交修改的本地仓库运行
python tools/run_mas_simple.py \
    --repo /path/to/your/repo \
    --issue "修复问题描述" \
    --allow-dirty

# 简写
python tools/run_mas_simple.py \
    --repo . \
    --issue "在当前目录工作" \
    --allow-dirty
```

### 使用 GitHub 仓库（自动缓存）

```bash
# 第一次运行 - 会克隆到本地缓存
python tools/run_mas_simple.py \
    --repo https://github.com/owner/repo \
    --issue "问题描述"

# 后续运行 - 复用缓存，速度快
python tools/run_mas_simple.py \
    --repo https://github.com/owner/repo \
    --issue "另一个问题"
```

## 核心功能

### 1. 支持未提交修改 (`--allow-dirty`)

**问题**：之前系统要求 git 仓库必须干净（没有未提交的修改）

**解决方案**：添加 `--allow-dirty` 标志

```bash
# 直接在开发中的仓库上工作
python tools/run_mas_simple.py \
    --repo /workspaces/my-project \
    --issue "测试新功能" \
    --allow-dirty
```

**注意**：
- 使用 `--allow-dirty` 时，所有未提交的修改都会被复制到 Docker 容器中
- 这对于开发和测试非常有用
- Agent 将在当前仓库状态下工作

### 2. 智能仓库缓存

**GitHub 仓库自动缓存到**：`~/.swe-agent/repo-cache/`

```bash
# 清理所有缓存
python tools/run_mas_simple.py --clear-cache

# 不使用缓存（总是克隆新的）
python tools/run_mas_simple.py \
    --repo https://github.com/owner/repo \
    --issue "..." \
    --no-cache
```

### 3. 灵活的问题输入

```bash
# 直接文本
--issue "修复登录 bug"

# 从文件读取
--issue issue.md

# 从 GitHub Issue 读取
--issue https://github.com/owner/repo/issues/123
```

## 常见使用场景

### 场景 1：本地开发调试

```bash
# 在当前工作目录运行，包含所有未提交的修改
cd /path/to/my-project
python /path/to/swe-agent/tools/run_mas_simple.py \
    --repo . \
    --issue "分析这个 bug" \
    --allow-dirty
```

### 场景 2：分析 GitHub 项目

```bash
# 自动克隆并分析
python tools/run_mas_simple.py \
    --repo https://github.com/django/django \
    --issue "性能优化建议"
```

### 场景 3：批量测试

```bash
#!/bin/bash
# 测试多个问题

REPO="/path/to/repo"

for issue in issue1.txt issue2.txt issue3.txt; do
    python tools/run_mas_simple.py \
        --repo "$REPO" \
        --issue "$issue" \
        --allow-dirty \
        --request-id "test-$(basename $issue .txt)"
done
```

## 配置选项

### 最小配置（仅需要的参数）

```bash
python tools/run_mas_simple.py --repo <path> --issue <desc>
```

### 完整配置

```bash
python tools/run_mas_simple.py \
    --repo <path_or_url> \
    --issue <description> \
    --allow-dirty \
    --rca-config config/agents/rca_agent.yaml \
    --patch-config config/agents/patch_agent.yaml \
    --output-dir trajectories/my_run \
    --docker-image python:3.11 \
    --request-id my-task \
    --neo4j-uri bolt://localhost:7687 \
    --neo4j-user neo4j \
    --neo4j-password password
```

## 输出结果

结果保存在 `trajectories/marrs_<timestamp>/` 目录：

```
trajectories/marrs_20250109_143022/
├── rca/default/          # RCA Agent 轨迹
├── patch/default/        # Patch Agent 轨迹
├── workflow_summary_default.json  # 详细 JSON 输出
└── workflow_summary_default.txt   # 人类可读摘要
```

查看结果：
```bash
# 查看最新的摘要
cat trajectories/marrs_*/workflow_summary_*.txt | tail -100

# 使用 SWE-agent inspector
sweagent inspector
```

## 故障排除

### "Local git repository is dirty"

**解决**：添加 `--allow-dirty` 标志

```bash
python tools/run_mas_simple.py --repo . --issue "..." --allow-dirty
```

### "Docker permission denied"

```bash
# 修复 Docker socket 权限
sudo chmod 666 /var/run/docker.sock

# 或添加用户到 docker 组
sudo usermod -aG docker $USER
```

### "Failed to clone repository"

```bash
# 使用 GitHub token（对于私有仓库）
export GITHUB_TOKEN=your_token_here

# 清理缓存重试
python tools/run_mas_simple.py --clear-cache
```

## 与原版本对比

### 旧版本 (run_mas.py)
```bash
python tools/run_mas.py \
    --repo https://github.com/owner/repo \
    --issue "..." \
    --rca_config config/agents/rca_agent.yaml \
    --patch_config config/agents/patch_agent.yaml \
    --docker_image python:3.11 \
    --output_dir trajectories/my_run
```

### 新版本 (run_mas_simple.py)
```bash
python tools/run_mas_simple.py \
    --repo https://github.com/owner/repo \
    --issue "..."
    # 所有其他参数都有默认值！
```

### 新增特性

1. ✅ 支持未提交修改 (`--allow-dirty`)
2. ✅ 自动仓库缓存（避免重复克隆）
3. ✅ 更少的必需参数（只需 2 个）
4. ✅ 更清晰的命名（使用 `-` 而不是 `_`）
5. ✅ 智能默认值（无需指定所有选项）

## 最佳实践

1. **本地开发**：始终使用 `--allow-dirty`
2. **生产环境**：使用干净的 git 仓库或提交修改
3. **大型仓库**：利用缓存机制，避免 `--no-cache`
4. **调试**：使用有意义的 `--request-id` 来区分不同运行
5. **自动化**：从文件读取问题描述，便于批处理

## 环境变量

支持的环境变量：

```bash
export GITHUB_TOKEN=<token>      # GitHub 认证
export NEO4J_URI=<uri>           # Neo4j 连接
export NEO4J_USER=<user>         # Neo4j 用户
export NEO4J_PASSWORD=<password> # Neo4j 密码
```
