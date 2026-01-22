#!/usr/bin/env bash
# Install verification helper tools

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Add bin directory to PATH in agent environment
BIN_DIR="${SCRIPT_DIR}/bin"

# Make all scripts executable
chmod +x "${BIN_DIR}"/*

# Symlink to standard location if needed
if [ -n "${SWE_AGENT_TOOLS_DIR:-}" ]; then
    mkdir -p "${SWE_AGENT_TOOLS_DIR}/verification_helpers"
    ln -sf "${BIN_DIR}"/* "${SWE_AGENT_TOOLS_DIR}/verification_helpers/"
fi

echo "Verification helpers installed successfully"
