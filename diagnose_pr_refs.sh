#!/bin/bash
# 诊断 GitCode 的 PR 引用格式

REPO_URL="https://gitcode.com/openharmony/distributeddatamgr_relational_store.git"
PR_NUMBER="2983"

echo "🔍 诊断 GitCode PR 引用格式"
echo "======================================"
echo "仓库: $REPO_URL"
echo "PR: #$PR_NUMBER"
echo ""

# 创建临时目录
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

echo "📥 克隆仓库..."
git clone "$REPO_URL" repo
cd repo

echo ""
echo "======================================"
echo "📋 查找所有可能的 PR 引用"
echo "======================================"

echo ""
echo "1️⃣ 查找包含 'pull' 的引用:"
git ls-remote origin | grep -i pull | head -20

echo ""
echo "2️⃣ 查找包含 'merge' 的引用:"
git ls-remote origin | grep -i merge | head -20

echo ""
echo "3️⃣ 查找包含 'pr' 的引用:"
git ls-remote origin | grep -i "/pr" | head -20

echo ""
echo "4️⃣ 查找包含数字 '$PR_NUMBER' 的引用:"
git ls-remote origin | grep "$PR_NUMBER"

echo ""
echo "5️⃣ 查看所有远程分支:"
git ls-remote origin | grep "refs/heads" | head -20

echo ""
echo "======================================"
echo "💡 提示"
echo "======================================"
echo "如果上面没有找到 PR 引用，可能的原因："
echo "1. GitCode 不支持通过 git 直接获取 PR"
echo "2. 需要使用 GitCode API"
echo "3. PR 已经合并，分支已删除"
echo ""
echo "临时目录: $TEMP_DIR"
echo "======================================"
