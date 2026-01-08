# Docker网络连接问题 - 长期解决方案

## 问题描述

在devcontainer环境中运行Harmony MAS时，出现Docker容器网络连接问题：
- 错误信息：`Runtime did not start within timeout`
- 根本原因：swerex使用`127.0.0.1`连接容器，但在devcontainer中`localhost`指向容器自身而非Docker宿主机

## 问题根源分析

1. **网络隔离**：
   - devcontainer运行在`swe-agent_devcontainer_default`网络（172.18.0.0/16）
   - swerex启动的容器默认运行在`bridge`网络（172.17.0.0/16）
   - 两个容器在不同的Docker网络中

2. **连接地址问题**：
   - swerex硬编码使用`127.0.0.1`连接运行时（见`/usr/local/lib/python3.11/site-packages/swerex/deployment/docker.py:271`）
   - 在devcontainer中，`127.0.0.1`指向devcontainer本身，而不是宿主机或其他容器

3. **端口映射限制**：
   - 即使使用`-p`映射端口，端口映射到宿主机而非devcontainer
   - devcontainer无法直接访问宿主机的`localhost`端口

## 长期解决方案

### 方案1：使用同一Docker网络（当前采用）

**优点**：不需要修改swerex源代码，容器间可直接通信
**缺点**：需要知道容器名称，swerex仍使用`127.0.0.1`

**实现**：在`tools/run_harmony_mas.py`中添加网络配置

```python
env_config = EnvironmentConfig(
    repo=repo,
    deployment={
        "type": "docker",
        "image": args.image,
        "startup_timeout": 600.0,
        "docker_args": ["--network", "swe-agent_devcontainer_default"],
    },
)
```

**限制**：虽然容器在同一网络，但swerex仍尝试连接`127.0.0.1`而非容器IP/名称

---

### 方案2：修补swerex库添加host参数（推荐）

**优点**：彻底解决问题，可适配各种网络环境
**缺点**：需要修改第三方库或提交上游PR

#### 2.1 临时本地补丁

创建本地补丁文件`sweagent/deployment/docker_patched.py`：

```python
"""Patched DockerDeployment with configurable host."""
import swerex.deployment.docker as docker_module
from swerex.deployment.config import DockerDeploymentConfig
from swerex.runtime.config import RemoteRuntimeConfig
from swerex.runtime.remote import RemoteRuntime
from pydantic import Field


class PatchedDockerDeploymentConfig(DockerDeploymentConfig):
    """Extended config with custom host support."""
    runtime_host: str | None = Field(default=None, description="Custom host for runtime connection (default: 127.0.0.1)")


class PatchedDockerDeployment(docker_module.DockerDeployment):
    """DockerDeployment with configurable runtime host."""

    def __init__(self, **kwargs):
        # Extract custom host before passing to parent
        self._custom_host = kwargs.pop('runtime_host', None)
        super().__init__(**kwargs)

    async def start(self):
        """Start deployment with custom host support."""
        # Use parent's start logic but override runtime creation
        await self._start_container_and_runtime()

    async def _start_container_and_runtime(self):
        """Modified start logic with custom host."""
        # Start container (copy parent logic)
        self._pull_image()
        if self._config.port is None:
            from swerex.utils.free_port import find_free_port
            self._config.port = find_free_port()

        self._container_name = self._get_container_name()
        token = self._get_token()

        # Build docker run command
        import subprocess, shlex
        platform_arg = [] if self._config.platform is None else ["--platform", self._config.platform]
        rm_arg = ["--rm"] if self._config.remove_container else []

        cmds = [
            self._config.container_runtime,
            "run",
            *rm_arg,
            "-p", f"{self._config.port}:8000",
            *platform_arg,
            *self._config.docker_args,
            "--name", self._container_name,
            self._config.image,
            *self._get_swerex_start_cmd(token),
        ]

        self.logger.info(f"Starting container {self._container_name} with image {self._config.image}")
        self._container_process = subprocess.Popen(cmds, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Custom host logic
        runtime_host = self._custom_host
        if runtime_host is None:
            # Auto-detect: if in devcontainer, use gateway IP
            runtime_host = self._detect_runtime_host()

        self.logger.info(f"Connecting to runtime at {runtime_host}:{self._config.port}")
        self._runtime = RemoteRuntime.from_config(
            RemoteRuntimeConfig(
                host=runtime_host,
                port=self._config.port,
                timeout=self._runtime_timeout,
                auth_token=token
            )
        )

        import time
        t0 = time.time()
        await self._wait_until_alive(timeout=self._config.startup_timeout)
        self.logger.info(f"Runtime started in {time.time() - t0:.2f}s")

    def _detect_runtime_host(self) -> str:
        """Auto-detect appropriate runtime host."""
        import os, subprocess

        # Check if in container (devcontainer)
        if not (os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")):
            return "http://127.0.0.1"

        # In container: check if using same network
        if "--network" in self._config.docker_args:
            network_idx = self._config.docker_args.index("--network") + 1
            if network_idx < len(self._config.docker_args):
                container_network = self._config.docker_args[network_idx]
                # If same network, use container name
                if container_network == "swe-agent_devcontainer_default":
                    return f"http://{self._container_name}"

        # Fallback: use gateway IP
        try:
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True, text=True, timeout=1
            )
            if result.returncode == 0 and "via" in result.stdout:
                gateway = result.stdout.split("via")[1].split()[0].strip()
                return f"http://{gateway}"
        except Exception:
            pass

        return "http://127.0.0.1"
```

然后在`tools/run_harmony_mas.py`中使用：

```python
from sweagent.deployment.docker_patched import PatchedDockerDeploymentConfig

env_config = EnvironmentConfig(
    repo=repo,
    deployment={
        "type": "docker",
        "image": args.image,
        "startup_timeout": 600.0,
        "docker_args": ["--network", "swe-agent_devcontainer_default"],
        "runtime_host": None,  # Auto-detect
    },
)
```

#### 2.2 提交上游PR

向swerex项目提交PR，在`DockerDeploymentConfig`中添加`runtime_host`参数：

```python
# In swerex/deployment/config.py
class DockerDeploymentConfig(BaseModel):
    ...
    runtime_host: str | None = None
    """Custom host for connecting to runtime (default: 127.0.0.1). Useful in nested container environments."""
```

```python
# In swerex/deployment/docker.py line 270
host = self._config.runtime_host or "http://127.0.0.1"
self._runtime = RemoteRuntime.from_config(
    RemoteRuntimeConfig(host=host, port=self._config.port, timeout=self._runtime_timeout, auth_token=token)
)
```

---

### 方案3：使用环境变量

修改swerex支持环境变量配置（需要上游PR）：

```bash
export SWEREX_RUNTIME_HOST="http://172.18.0.1"
```

---

### 方案4：devcontainer配置优化

修改`.devcontainer/devcontainer.json`：

```json
{
  "runArgs": [
    "--network=host"  // 使用host网络（可能有安全问题）
  ]
}
```

或使用Docker-in-Docker方式：

```json
{
  "features": {
    "ghcr.io/devcontainers/features/docker-in-docker:2": {}
  }
}
```

---

## 当前采用的临时方案

在`tools/run_harmony_mas.py`中：

1. 增加启动超时：`startup_timeout: 600.0`
2. 使用devcontainer网络：`docker_args: ["--network", "swe-agent_devcontainer_default"]`

**问题**：虽然容器在同一网络，但swerex仍使用`127.0.0.1`导致连接失败

---

## 推荐的最终解决方案

**短期**（立即可用）：
- 实现方案2.1的本地补丁
- 在`sweagent/deployment/docker_patched.py`中创建修补版本
- 修改环境配置使用补丁版本

**长期**（贡献开源）：
- 向swerex提交PR添加`runtime_host`参数（方案2.2）
- 同时添加自动检测devcontainer环境的逻辑
- 合并后更新依赖版本

---

## 验证步骤

1. 检查容器网络：
```bash
export DOCKER_API_VERSION=1.43
docker ps --format "{{.Names}}\t{{.Networks}}"
```

2. 测试容器连通性：
```bash
# 通过容器名
curl http://<container-name>:8000/health

# 通过网关IP
curl http://172.18.0.1:<port>/health
```

3. 检查运行时日志：
```bash
tail -f trajectories/harmony_mas_*/output.log
```
