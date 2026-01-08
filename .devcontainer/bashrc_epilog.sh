# Set Docker API version to match host daemon
export DOCKER_API_VERSION=1.43

# Check and fix Docker permissions on shell startup
# Only run if Docker socket exists and we haven't checked in this session
if [ -S "/var/run/docker.sock" ] && [ -z "$DOCKER_PERMS_CHECKED" ]; then
    # Quick permission check
    if ! docker ps >/dev/null 2>&1; then
        # Only show message if there's actually a problem
        SOCKET_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null)
        DOCKER_GID=$(getent group docker | cut -d: -f3 2>/dev/null)

        if [ "$SOCKET_GID" != "$DOCKER_GID" ] && [ -n "$DOCKER_GID" ]; then
            echo "🔧 Fixing Docker permissions..."
            if sudo -n chown root:docker /var/run/docker.sock 2>/dev/null; then
                echo "✓ Docker permissions fixed"
            else
                echo "⚠ Warning: Could not fix Docker permissions automatically"
                echo "  Run: sudo chown root:docker /var/run/docker.sock"
            fi
        fi
    fi
    # Mark as checked for this session
    export DOCKER_PERMS_CHECKED=1
fi

if [ -z "$(docker images -q sweagent/swe-agent 2> /dev/null)" ]; then
  echo "⚠️ Please wait for the postCreateCommand to start and finish (a new window will appear shortly) ⚠️"
fi

echo "Here's an example SWE-agent command to try out:"

echo "sweagent run \\
  --agent.model.name=claude-sonnet-4-20250514 \\
  --agent.model.per_instance_cost_limit=2.00 \\
  --env.repo.github_url=https://github.com/SWE-agent/test-repo \\
  --problem_statement.github_url=https://github.com/SWE-agent/test-repo/issues/1 \\
"
