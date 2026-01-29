#!/bin/bash
# 简化版 PR 基准提交提取脚本
# 用法: ./get_pr_base_simple.sh <repo_url> <pr_number> [target_branch]

set -e

if [ $# -lt 2 ]; then
    echo "用法: $0 <repo_url> <pr_number> [target_branch]"
    echo "示例: $0 https://gitcode.com/openharmony/distributeddatamgr_relational_store.git 2983 master"
    exit 1
fi

REPO_URL=$1
PR_NUMBER=$2
TARGET_BRANCH=${3:-master}  # 默认是 master

# 从 URL 提取仓库名
REPO_NAME=$(basename "$REPO_URL" .git)
OUTPUT_DIR="pr_base_repos/${REPO_NAME}_PR${PR_NUMBER}"

echo "=========================================="
echo "🔍 处理 PR #${PR_NUMBER}"
echo "📦 仓库: ${REPO_URL}"
echo "🎯 目标分支: ${TARGET_BRANCH}"
echo "=========================================="

# 克隆仓库（如果不存在）
if [ ! -d "$OUTPUT_DIR" ]; then
    echo "📥 克隆仓库..."
    git clone "$REPO_URL" "$OUTPUT_DIR"
else
    echo "📂 仓库已存在: $OUTPUT_DIR"
fi

cd "$OUTPUT_DIR"

# 尝试多种 PR 引用格式
echo "🔍 尝试获取 PR 分支..."

# 格式 1: GitLab/GitCode 风格 (merge-requests/NUMBER/head) - GitCode 使用这个
if git fetch origin "merge-requests/${PR_NUMBER}/head:pr-${PR_NUMBER}" 2>/dev/null; then
    echo "✅ 使用 GitLab/GitCode 风格引用成功"
# 格式 2: GitHub 风格 (pull/NUMBER/head)
elif git fetch origin "pull/${PR_NUMBER}/head:pr-${PR_NUMBER}" 2>/dev/null; then
    echo "✅ 使用 GitHub 风格引用成功"
# 格式 3: Gitee 风格 (pull/NUMBER)
elif git fetch origin "pull/${PR_NUMBER}:pr-${PR_NUMBER}" 2>/dev/null; then
    echo "✅ 使用 Gitee 风格引用成功"
else
    echo "❌ 无法获取 PR 分支，尝试列出可用的引用..."
    echo "可用的 pull/merge 引用:"
    git ls-remote origin | grep -E "(pull|merge)" | head -20
    echo ""
    echo "请手动检查正确的引用格式，然后运行:"
    echo "  git fetch origin <正确的引用>:pr-${PR_NUMBER}"
    exit 1
fi

# 确保目标分支存在
if ! git rev-parse "origin/${TARGET_BRANCH}" >/dev/null 2>&1; then
    echo "⚠️  目标分支 origin/${TARGET_BRANCH} 不存在"
    echo "可用的远程分支:"
    git branch -r
    exit 1
fi

# 找到 merge base（共同祖先）
echo "🔍 查找基准提交..."
BASE_COMMIT=$(git merge-base "pr-${PR_NUMBER}" "origin/${TARGET_BRANCH}")

if [ -z "$BASE_COMMIT" ]; then
    echo "❌ 无法找到基准提交"
    exit 1
fi

# 获取提交信息
BASE_MSG=$(git log -1 --format="%s" "$BASE_COMMIT")
HEAD_COMMIT=$(git rev-parse "pr-${PR_NUMBER}")

echo ""
echo "✅ 找到基准提交!"
echo "   📍 基准提交: ${BASE_COMMIT:0:8}"
echo "   📝 提交信息: $BASE_MSG"
echo "   🔝 PR 提交: ${HEAD_COMMIT:0:8}"
echo ""

# 创建基准分支
BASE_BRANCH="base-before-pr${PR_NUMBER}"
echo "🌿 创建分支: $BASE_BRANCH"

# 删除旧分支（如果存在）
git branch -D "$BASE_BRANCH" 2>/dev/null || true

# 创建并切换到基准分支
git checkout -b "$BASE_BRANCH" "$BASE_COMMIT"

echo ""
echo "=========================================="
echo "✨ 完成!"
echo "=========================================="
echo "📂 仓库路径: $(pwd)"
echo "🌿 当前分支: $BASE_BRANCH (修复前的代码)"
echo ""
echo "📋 后续操作:"
echo "   # 查看 PR 的修改"
echo "   git diff $BASE_BRANCH pr-${PR_NUMBER}"
echo ""
echo "   # 查看修改的文件"
echo "   git diff --name-only $BASE_BRANCH pr-${PR_NUMBER}"
echo ""
echo "   # 切换到 PR 分支（修复后的代码）"
echo "   git checkout pr-${PR_NUMBER}"
echo ""
echo "   # 切换回修复前的代码"
echo "   git checkout $BASE_BRANCH"
echo "=========================================="

# 保存信息到文件
INFO_FILE="../PR${PR_NUMBER}_info.txt"
cat > "$INFO_FILE" << EOF
PR #${PR_NUMBER} 信息
==================
仓库: ${REPO_URL}
本地路径: $(pwd)
目标分支: ${TARGET_BRANCH}
基准提交: ${BASE_COMMIT}
提交信息: ${BASE_MSG}
PR 提交: ${HEAD_COMMIT}
基准分支: ${BASE_BRANCH}

查看修改:
  cd $(pwd)
  git diff ${BASE_COMMIT} ${HEAD_COMMIT}
EOF

echo "💾 信息已保存到: $INFO_FILE"
