#!/usr/bin/env bash

set -euo pipefail
set -x

# Install Python package
pip install -e '.'

# Fix Docker permissions
echo "Fixing Docker permissions..."
./.devcontainer/fix_docker_permissions.sh || echo "Warning: Docker permissions fix failed (continuing anyway)"

# Install static analysis tools
echo "Installing static analysis tools..."
bash tools/static_analysis/install.sh || echo "Warning: Static analysis tools installation had issues (continuing anyway)"

# Wait for Neo4j to be ready
echo "Waiting for Neo4j to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:7474 > /dev/null 2>&1; then
        echo "Neo4j is ready!"
        break
    fi
    echo "Waiting for Neo4j... ($i/30)"
    sleep 2
done

# Verify Neo4j connection
echo "Verifying Neo4j connection..."
python3 -c "
from neo4j import GraphDatabase
import os
try:
    driver = GraphDatabase.driver(
        os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
        auth=(os.getenv('NEO4J_USER', 'neo4j'), os.getenv('NEO4J_PASSWORD', 'swe-agent-local'))
    )
    driver.verify_connectivity()
    print('✓ Neo4j connection successful!')
    driver.close()
except Exception as e:
    print(f'⚠ Neo4j connection failed: {e}')
    print('This is okay - indexing will be skipped if Neo4j is unavailable')
" || echo "Neo4j verification failed (continuing anyway)"

echo "Environment setup complete!"

