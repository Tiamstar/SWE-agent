#!/bin/bash
# Quick start script for testing Harmony MAS with Defects4C

set -e

echo "=========================================="
echo "Defects4C + Harmony MAS Quick Start"
echo "=========================================="
echo ""

# Check if requests is installed
if ! python -c "import requests" 2>/dev/null; then
    echo "Installing required package: requests"
    pip install requests
fi

echo "Step 1: Testing API connection..."
echo ""

# Test API connection
python -c "
import requests
try:
    response = requests.get('https://defects4c.wj2ai.com/list_defects_bugid', timeout=10)
    if response.status_code == 200:
        data = response.json()
        print(f'✅ API connection successful!')
        print(f'   Total defects available: {len(data.get(\"defects\", []))}')
    else:
        print(f'❌ API returned status code: {response.status_code}')
        exit(1)
except Exception as e:
    print(f'❌ Failed to connect to Defects4C API: {e}')
    exit(1)
"

echo ""
echo "Step 2: Listing recommended test bugs..."
echo ""

# Get bug list for cppcheck
python -c "
import json
from pathlib import Path

bugs_file = Path('defects4c-master/defectsc_tpl/projects_v1/danmar___cppcheck/bugs_list_new.json')

if bugs_file.exists():
    with open(bugs_file) as f:
        bugs = json.load(f)

    print('Recommended test bugs from cppcheck project:')
    print('')

    for i, bug in enumerate(bugs[:5], 1):
        commit = bug['commit_after']
        bug_type = bug.get('type', {}).get('name', 'Unknown')
        print(f'{i}. Bug ID: danmar___cppcheck@{commit}')
        print(f'   Type: {bug_type}')
        print(f'   Date: {bug[\"commit_date\"]}')
        print('')
else:
    print('⚠️  Bug list file not found. Using default bug ID.')
    print('')
    print('1. Bug ID: danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082')
    print('   Type: Logic Organization: Improper Condition Organization')
    print('')
"

echo "Step 3: Testing with first bug (API only mode)..."
echo ""

# Test with first bug
BUG_ID="danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082"

python tools/test_harmony_with_defects4c.py \
    --bug_id "$BUG_ID" \
    --api_only

echo ""
echo "=========================================="
echo "Quick Start Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Review the integration guide:"
echo "   cat docs/DEFECTS4C_INTEGRATION.md"
echo ""
echo "2. Integrate your Harmony MAS system by editing:"
echo "   tools/test_harmony_with_defects4c.py"
echo ""
echo "3. Run a full test with your system:"
echo "   python tools/test_harmony_with_defects4c.py \\"
echo "       --bug_id \"$BUG_ID\" \\"
echo "       --repo_path /path/to/cppcheck"
echo ""
echo "4. For batch testing, see:"
echo "   docs/DEFECTS4C_INTEGRATION.md#批量测试"
echo ""
