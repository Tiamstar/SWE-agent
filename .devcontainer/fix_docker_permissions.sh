#!/usr/bin/env bash
# Docker Permissions Fix Script
# This script ensures the Docker socket has proper group permissions
# so that users in the docker group can access it without sudo.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Docker socket path
DOCKER_SOCK="/var/run/docker.sock"

# Function to log messages
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker socket exists
if [ ! -S "$DOCKER_SOCK" ]; then
    log_error "Docker socket not found at $DOCKER_SOCK"
    log_error "Make sure Docker is running and the socket is mounted"
    exit 1
fi

# Get current socket ownership
SOCKET_GROUP=$(stat -c '%G' "$DOCKER_SOCK" 2>/dev/null || stat -f '%Sg' "$DOCKER_SOCK" 2>/dev/null)
SOCKET_GID=$(stat -c '%g' "$DOCKER_SOCK" 2>/dev/null || stat -f '%g' "$DOCKER_SOCK" 2>/dev/null)

log_info "Docker socket group: $SOCKET_GROUP (GID: $SOCKET_GID)"

# Check if user is in docker group
DOCKER_GID=$(getent group docker | cut -d: -f3)
USER_GROUPS=$(id -G)

if echo "$USER_GROUPS" | grep -q "\b$DOCKER_GID\b"; then
    log_info "Current user is in docker group (GID: $DOCKER_GID)"

    # Check if socket has correct group
    if [ "$SOCKET_GID" != "$DOCKER_GID" ]; then
        log_warn "Docker socket group ($SOCKET_GID) does not match docker group ($DOCKER_GID)"
        log_info "Attempting to fix socket group ownership..."

        if sudo chown root:docker "$DOCKER_SOCK" 2>/dev/null; then
            log_info "✓ Successfully changed socket group to docker"
        else
            log_error "Failed to change socket group (may need manual intervention)"
            exit 1
        fi
    else
        log_info "✓ Docker socket already has correct group ownership"
    fi

    # Test Docker access
    if docker ps >/dev/null 2>&1; then
        log_info "✓ Docker access verified - 'docker ps' succeeded"
    else
        log_error "Docker access test failed - 'docker ps' returned an error"
        log_error "You may need to log out and log back in for group changes to take effect"
        exit 1
    fi
else
    log_error "Current user is not in docker group"
    log_info "Run: sudo usermod -aG docker \$USER"
    exit 1
fi

log_info "Docker permissions are correctly configured!"
