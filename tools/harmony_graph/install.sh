#!/bin/bash
# HarmonyOS Code Graph - Installation Script
# This script installs Python dependencies required for graph querying

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo "HarmonyOS Graph Tool Installation"
echo "=========================================="

# 1. 安装必需的Python依赖 (仅查询功能)
echo ""
echo "[1/2] Installing required Python dependencies..."
echo "  - neo4j (Neo4j database driver)"

pip install neo4j --quiet

echo "  ✓ neo4j installed successfully"

# 2. 设置执行权限
echo ""
echo "[2/2] Setting executable permissions..."

chmod +x "${SCRIPT_DIR}/bin"/*

echo "  ✓ All tools in bin/ are now executable"

echo ""
echo "=========================================="
echo "Installation complete!"
echo "=========================================="
echo ""
echo "The tools are ready for querying Neo4j databases."
echo ""
echo "IMPORTANT: Make sure you have:"
echo "  1. Neo4j database running and accessible"
echo "  2. Environment variables set (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)"
echo "  3. Code graph already indexed in the database"
echo ""
echo "Example usage:"
echo "  export NEO4J_URI='bolt://localhost:7687'"
echo "  export NEO4J_USER='neo4j'"
echo "  export NEO4J_PASSWORD='your_password'"
echo "  ${SCRIPT_DIR}/bin/inspect_file_topology main.cpp"
echo ""
echo "Note: Code indexing requires additional dependencies (tree-sitter)."
echo "For indexing support, run: pip install tree-sitter"
echo ""
