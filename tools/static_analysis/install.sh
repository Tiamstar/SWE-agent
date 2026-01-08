#!/bin/bash
# Static Analysis Tools Installation Script
# Installs C/C++ static analysis tools for Verification Agent
# NOTE: Tools may already be pre-installed in Docker image

# Don't exit on error - we want to continue even if some tools fail
set +e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo "C/C++ Static Analysis Tools Installation"
echo "=========================================="

# Check if tools are already installed (pre-installed in Dockerfile)
echo ""
echo "Checking for pre-installed tools..."
echo ""

CPPCHECK_INSTALLED=false
CLANG_TIDY_INSTALLED=false
CPPLINT_INSTALLED=false

if command -v cppcheck &> /dev/null; then
    echo "  ✓ cppcheck already installed: $(cppcheck --version | head -n1)"
    CPPCHECK_INSTALLED=true
else
    echo "  ✗ cppcheck not found"
fi

if command -v clang-tidy &> /dev/null; then
    echo "  ✓ clang-tidy already installed: $(clang-tidy --version | head -n1)"
    CLANG_TIDY_INSTALLED=true
else
    echo "  ✗ clang-tidy not found"
fi

if command -v cpplint &> /dev/null; then
    echo "  ✓ cpplint already installed"
    CPPLINT_INSTALLED=true
else
    echo "  ✗ cpplint not found"
fi

# If all tools are installed, we're done
if [ "$CPPCHECK_INSTALLED" = true ] && [ "$CLANG_TIDY_INSTALLED" = true ] && [ "$CPPLINT_INSTALLED" = true ]; then
    echo ""
    echo "=========================================="
    echo "All tools already installed - skipping!"
    echo "=========================================="
    exit 0
fi

echo ""
echo "Installing missing tools..."
echo ""

# Check if we're in a Debian/Ubuntu environment
if command -v apt-get &> /dev/null; then
    # Install missing apt-based tools
    if [ "$CPPCHECK_INSTALLED" = false ] || [ "$CLANG_TIDY_INSTALLED" = false ]; then
        echo "[1/2] Installing missing apt packages..."

        # Check if we have root/sudo permissions
        if [ "$EUID" -eq 0 ] || sudo -n true 2>/dev/null; then
            # Use sudo if not root
            SUDO_CMD=""
            [ "$EUID" -ne 0 ] && SUDO_CMD="sudo"

            # Update package list
            $SUDO_CMD apt-get update -qq 2>&1 | grep -v "^Get:" || true

            # Install missing tools
            PACKAGES_TO_INSTALL=""
            [ "$CPPCHECK_INSTALLED" = false ] && PACKAGES_TO_INSTALL="$PACKAGES_TO_INSTALL cppcheck"
            [ "$CLANG_TIDY_INSTALLED" = false ] && PACKAGES_TO_INSTALL="$PACKAGES_TO_INSTALL clang-tidy"

            if [ -n "$PACKAGES_TO_INSTALL" ]; then
                $SUDO_CMD apt-get install -y -qq $PACKAGES_TO_INSTALL 2>&1 | grep -v "^Selecting\|^Preparing\|^Unpacking" || {
                    echo "  ⚠ Warning: Failed to install some packages via apt-get"
                    echo "  This is okay - checks will be skipped for unavailable tools"
                }
            fi
        else
            echo "  ⚠ Warning: No sudo permissions - cannot install via apt-get"
            echo "  This is okay - checks will be skipped for unavailable tools"
        fi
    fi

    # Install cpplint via pip if missing
    if [ "$CPPLINT_INSTALLED" = false ]; then
        echo ""
        echo "[2/2] Installing cpplint via pip..."
        pip install cpplint --quiet || {
            echo "  ⚠ Warning: Failed to install cpplint via pip"
            echo "  This is okay - cpplint checks will be skipped"
        }
    fi
else
    echo ""
    echo "⚠ Non-Debian environment detected"
    echo "Static analysis tools cannot be automatically installed"
    echo "Tools will gracefully skip checks if not available"

    # Try pip-based tools at least
    if [ "$CPPLINT_INSTALLED" = false ]; then
        echo ""
        echo "Attempting to install pip-based tools..."
        pip install cpplint --quiet || echo "  ⚠ cpplint installation failed"
    fi
fi

echo ""
echo "=========================================="
echo "Installation complete!"
echo "=========================================="
echo ""
echo "Available static analysis tools:"
command -v cppcheck &> /dev/null && echo "  ✓ cppcheck: $(which cppcheck)" || echo "  ✗ cppcheck: not available"
command -v clang-tidy &> /dev/null && echo "  ✓ clang-tidy: $(which clang-tidy)" || echo "  ✗ clang-tidy: not available"
command -v cpplint &> /dev/null && echo "  ✓ cpplint: $(which cpplint)" || echo "  ✗ cpplint: not available"
echo ""
echo "Note: Verification Agent will gracefully handle missing tools"
echo "by returning CHECK_SKIPPED status when tools are unavailable."
echo ""

# Always exit successfully - missing tools are acceptable
exit 0
