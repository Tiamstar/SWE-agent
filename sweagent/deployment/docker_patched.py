"""Patched DockerDeployment with configurable runtime host.

This module provides a patched version of swerex's DockerDeployment that supports
custom runtime host configuration. This is necessary for nested container environments
like devcontainers where localhost (127.0.0.1) points to the container itself rather
than the Docker host.

Usage:
    This patched deployment is automatically used by run_harmony_mas.py when
    SWEREX_USE_PATCHED_DOCKER environment variable is set.
"""

import logging
import os
import subprocess
from typing import Any

from swerex.deployment.docker import DockerDeployment as _OriginalDockerDeployment
from swerex.runtime.config import RemoteRuntimeConfig
from swerex.runtime.remote import RemoteRuntime


class DockerDeploymentWithCustomHost(_OriginalDockerDeployment):
    """DockerDeployment with auto-detecting runtime host for devcontainer environments.

    This class extends swerex's DockerDeployment to support connecting to containers
    in nested Docker environments (e.g., devcontainer). It automatically detects the
    appropriate host address based on the network configuration.

    Detection logic:
    1. If containers share the same Docker network → use container name
    2. If in devcontainer → use Docker gateway IP (usually 172.18.0.1)
    3. Otherwise → use standard 127.0.0.1
    """

    def __init__(self, *, logger: logging.Logger | None = None, **kwargs: Any):
        """Initialize with optional runtime_host parameter."""
        # Extract custom host parameter (not in original config)
        self._custom_runtime_host = kwargs.pop("runtime_host", None)
        super().__init__(logger=logger, **kwargs)

    async def start(self):
        """Override start to use custom runtime host detection."""
        # Use parent's pull and container start logic
        self._pull_image()

        # Find free port if not specified
        if self._config.port is None:
            from swerex.utils.free_port import find_free_port

            self._config.port = find_free_port()

        # Get container name and auth token
        self._container_name = self._get_container_name()
        token = self._get_token()

        # Build docker run command (same as parent)
        import shlex

        platform_arg = [] if self._config.platform is None else ["--platform", self._config.platform]
        rm_arg = ["--rm"] if self._config.remove_container else []

        image_id = self._config.image
        cmds = [
            self._config.container_runtime,
            "run",
            *rm_arg,
            "-p",
            f"{self._config.port}:8000",
            *platform_arg,
            *self._config.docker_args,
            "--name",
            self._container_name,
            image_id,
            *self._get_swerex_start_cmd(token),
        ]
        cmd_str = shlex.join(cmds)

        self.logger.info(
            f"Starting container {self._container_name} with image {self._config.image} serving on port {self._config.port}"
        )
        self.logger.debug(f"Command: {cmd_str!r}")

        # Start container
        self._container_process = subprocess.Popen(cmds, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._hooks.on_custom_step("Starting runtime")

        # Detect appropriate runtime host and port
        runtime_host, runtime_port = self._detect_runtime_endpoint()
        self.logger.info(f"Connecting to runtime at {runtime_host}:{runtime_port}")

        # Create runtime with custom host
        self._runtime = RemoteRuntime.from_config(
            RemoteRuntimeConfig(
                host=runtime_host, port=runtime_port, timeout=self._runtime_timeout, auth_token=token
            )
        )

        # Wait for runtime to start
        import time

        t0 = time.time()
        await self._wait_until_alive(timeout=self._config.startup_timeout)
        self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

    def _detect_runtime_endpoint(self) -> tuple[str, int]:
        """Auto-detect appropriate runtime host and port based on environment.

        Returns:
            tuple[str, int]: (host_url, port) for connecting to the runtime.
                When using container name, port is 8000 (container internal).
                When using localhost/IP, port is the mapped port.
        """
        # If explicitly set, use that
        if self._custom_runtime_host:
            host = self._custom_runtime_host
            if not host.startswith("http"):
                host = f"http://{host}"
            self.logger.debug(f"Using explicitly configured runtime host: {host}")
            return (host, self._config.port)

        # Check if we're in a container (devcontainer)
        in_container = os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")

        if not in_container:
            # Not in a container, use localhost
            self.logger.debug("Not in container, using 127.0.0.1")
            return ("http://127.0.0.1", self._config.port)

        # We're in a container - check network configuration
        self.logger.debug("Running in container, detecting network configuration")

        # Check if using custom network (same network as devcontainer)
        if "--network" in self._config.docker_args:
            try:
                network_idx = self._config.docker_args.index("--network") + 1
                if network_idx < len(self._config.docker_args):
                    container_network = self._config.docker_args[network_idx]
                    self.logger.debug(f"Container using network: {container_network}")

                    # If using devcontainer network, containers can communicate directly
                    if "devcontainer" in container_network or container_network == "host":
                        # Use container name for direct communication with internal port 8000
                        self.logger.info(
                            f"Using container name for direct communication: {self._container_name}"
                        )
                        return (f"http://{self._container_name}", 8000)  # Use container's internal port!
            except (ValueError, IndexError):
                pass

        # Fallback: try to get Docker gateway IP
        try:
            result = subprocess.run(
                ["ip", "route", "show", "default"], capture_output=True, text=True, timeout=1, check=False
            )
            if result.returncode == 0 and "via" in result.stdout:
                gateway = result.stdout.split("via")[1].split()[0].strip()
                self.logger.info(f"Using Docker gateway IP: {gateway}")
                return (f"http://{gateway}", self._config.port)
        except (subprocess.TimeoutExpired, IndexError, Exception) as e:
            self.logger.warning(f"Failed to detect gateway IP: {e}")

        # Final fallback
        self.logger.warning("Could not detect appropriate host, using 127.0.0.1 (may fail in devcontainer)")
        return ("http://127.0.0.1", self._config.port)


def patch_swerex_docker_deployment():
    """Monkey-patch swerex to use our custom Docker deployment.

    This function should be called early in the application initialization
    to replace swerex's DockerDeployment with our patched version.
    """
    import swerex.deployment.docker
    import swerex.deployment.config

    # Save original for reference
    swerex.deployment.docker._OriginalDockerDeployment = swerex.deployment.docker.DockerDeployment

    # Replace with our patched version
    swerex.deployment.docker.DockerDeployment = DockerDeploymentWithCustomHost

    # Also patch the config's get_deployment method
    original_get_deployment = swerex.deployment.config.DockerDeploymentConfig.get_deployment

    def patched_get_deployment(self):
        from swerex.deployment.docker import DockerDeployment

        return DockerDeployment.from_config(self)

    swerex.deployment.config.DockerDeploymentConfig.get_deployment = patched_get_deployment
