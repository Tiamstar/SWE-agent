#!/bin/bash
# Batch testing script for Harmony MAS with Defects4C

set -e

# Configuration
WORK_DIR="work/defects4c_batch_$(date +%Y%m%d_%H%M%S)"
COORDINATOR_CONFIG="config/agents/coordinator_agent.yaml"
MAX_ITERATIONS=3
NUM_CANDIDATE_PATCHES=3
DOCKER_IMAGE="python:3.11"

# Create work directory
mkdir -p "$WORK_DIR"
LOG_DIR="$WORK_DIR/logs"
mkdir -p "$LOG_DIR"

# Define test bugs (you can modify this list)
BUGS=(
    # cppcheck bugs (recommended for testing)
    "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082"  # Logic Organization
    "danmar___cppcheck@caa6ff7c2a6ef64df53e04701944aaa4712a1915"  # Control Expression Error

    # Add more bugs here as needed
    # "fmtlib___fmt@<commit_sha>"
    # "CLIUtils___CLI11@<commit_sha>"
)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Defects4C Batch Testing"
echo "=========================================="
echo "Work directory: $WORK_DIR"
echo "Total bugs to test: ${#BUGS[@]}"
echo "=========================================="
echo ""

# Statistics
TOTAL=0
PASSED=0
FAILED=0

# Test each bug
for bug_id in "${BUGS[@]}"; do
    TOTAL=$((TOTAL + 1))

    echo ""
    echo "=========================================="
    echo "Testing bug $TOTAL/${#BUGS[@]}: $bug_id"
    echo "=========================================="

    # Create log file
    LOG_FILE="$LOG_DIR/${bug_id//\//_}.log"

    # Run test
    if python tools/run_defects4c_test.py \
        --bug_id "$bug_id" \
        --work_dir "$WORK_DIR" \
        --coordinator_config "$COORDINATOR_CONFIG" \
        --max_iterations "$MAX_ITERATIONS" \
        --num_candidate_patches "$NUM_CANDIDATE_PATCHES" \
        --docker_image "$DOCKER_IMAGE" \
        2>&1 | tee "$LOG_FILE"; then

        echo -e "${GREEN}✅ PASSED${NC}: $bug_id"
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}❌ FAILED${NC}: $bug_id"
        FAILED=$((FAILED + 1))
    fi
done

# Print summary
echo ""
echo "=========================================="
echo "BATCH TEST SUMMARY"
echo "=========================================="
echo "Total bugs tested: $TOTAL"
echo -e "${GREEN}Passed: $PASSED${NC}"
echo -e "${RED}Failed: $FAILED${NC}"
echo "Success rate: $(awk "BEGIN {printf \"%.1f\", ($PASSED/$TOTAL)*100}")%"
echo "=========================================="
echo ""
echo "Results saved to: $WORK_DIR/results/"
echo "Logs saved to: $LOG_DIR/"
echo ""

# Generate summary report
SUMMARY_FILE="$WORK_DIR/summary.txt"
{
    echo "Defects4C Batch Test Summary"
    echo "============================"
    echo "Date: $(date)"
    echo "Total: $TOTAL"
    echo "Passed: $PASSED"
    echo "Failed: $FAILED"
    echo "Success Rate: $(awk "BEGIN {printf \"%.1f\", ($PASSED/$TOTAL)*100}")%"
    echo ""
    echo "Test Results:"
    echo "-------------"

    for bug_id in "${BUGS[@]}"; do
        RESULT_FILE="$WORK_DIR/results/${bug_id//\//_}_result.json"
        if [ -f "$RESULT_FILE" ]; then
            SUCCESS=$(jq -r '.overall_success' "$RESULT_FILE")
            if [ "$SUCCESS" = "true" ]; then
                echo "✅ $bug_id"
            else
                ERROR=$(jq -r '.error // "Unknown error"' "$RESULT_FILE")
                echo "❌ $bug_id - $ERROR"
            fi
        else
            echo "⚠️  $bug_id - No result file"
        fi
    done
} > "$SUMMARY_FILE"

echo "Summary report saved to: $SUMMARY_FILE"
cat "$SUMMARY_FILE"
