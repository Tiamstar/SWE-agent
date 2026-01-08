# Harmony MAS Quick Start

## 快速开始指南

### 安装要求

- Python 3.11+
- Docker (用于运行环境)
- SWE-agent (已安装)

### 基本使用

```bash
# 1. 进入项目目录
cd /workspaces/SWE-agent

# 2. 运行Harmony MAS系统
python tools/run_harmony_mas.py \
    --repo_path /path/to/your/harmonyos/repo \
    --issue "src/foundation/ace/adapter.cpp:142: warning: Potential null pointer dereference"
```

### 系统架构

```
HarmonyCoordinator (协调器)
    ↓
    ├─→ Topology Agent (拓扑分析)
    ├─→ Temporal Agent (历史分析)
    ├─→ Patch Generation (补丁生成)
    ├─→ Review Agent (构建验证)
    └─→ Contract Agent (契约验证)
```

### 工作流程

1. **INITIALIZED**: 初始化共享环境
2. **ANALYSIS_TOPOLOGY**: 分析代码结构和依赖关系
3. **ANALYSIS_HISTORY**: 分析Git历史和变更模式
4. **PATCH_GENERATION**: 基于洞察生成候选补丁
5. **VERIFICATION_REVIEW**: 验证补丁（编译+契约检查）
6. **FINALIZING**: 选择最佳补丁
7. **FINISHED**: 完成

### 输出文件

```
trajectories/harmony_mas_<timestamp>/
├── state_<task_id>.json              # 共享状态对象
├── topology/<task_id>/                # 拓扑分析轨迹
├── temporal/<task_id>/                # 历史分析轨迹
├── review/<task_id>/                  # 构建验证轨迹
└── contract/<task_id>/                # 契约验证轨迹
```

### 核心文件

| 文件 | 说明 |
|------|------|
| `sweagent/agent/mas/shared_state.py` | 共享状态对象定义 |
| `sweagent/agent/mas/harmony_coordinator.py` | 协调器实现 |
| `config/agents/topology_agent.yaml` | 拓扑分析Agent配置 |
| `config/agents/temporal_agent.yaml` | 时序分析Agent配置 |
| `config/agents/review_agent.yaml` | 构建验证Agent配置 |
| `config/agents/contract_agent.yaml` | 契约验证Agent配置 |
| `tools/run_harmony_mas.py` | 运行脚本 |
| `docs/harmony_mas_guide.md` | 完整文档 |

### 与原RCA/Patch系统的区别

| 特性 | 原系统 | Harmony MAS |
|------|--------|-------------|
| Agent数量 | 2个 | 4+个 |
| 工作流 | 线性传递 | 状态机+迭代 |
| 状态管理 | 隐式 | 显式（SharedState） |
| 验证机制 | 可选 | 强制（编译+契约） |
| 重试机制 | 无 | 自动迭代 |
| 输出格式 | 非结构化 | 结构化JSON |
| 风险评估 | 无 | 量化评分（0.0-1.0） |

### 示例场景

#### 场景1: 修复空指针解引用警告

```bash
python tools/run_harmony_mas.py \
    --repo_path ~/projects/harmonyos-foundation \
    --issue "foundation/ace/adapter.cpp:142: warning: potential null pointer dereference of 'ptr'" \
    --max_iterations 3
```

#### 场景2: 修复内存泄漏警告

```bash
python tools/run_harmony_mas.py \
    --repo_path ~/projects/harmonyos-multimedia \
    --issue "multimedia/camera/camera_manager.cpp:256: warning: memory leak on error path" \
    --task_id MEMORY-LEAK-001 \
    --output_dir ./outputs
```

#### 场景3: 自定义Docker镜像

```bash
python tools/run_harmony_mas.py \
    --repo_path ~/projects/harmonyos-kernel \
    --issue "kernel/syscall.c:89: warning: race condition detected" \
    --image harmonyos-builder:latest \
    --max_iterations 5
```

### 故障排除

#### 问题: Agent返回非结构化输出

**解决**: 检查agent配置文件的system_template是否强调"仅返回JSON"

#### 问题: 补丁验证反复失败

**解决**:
- 增加 `--max_iterations` 值
- 提供更详细的警告描述
- 检查harmony_graph工具是否正常工作

#### 问题: 环境初始化失败

**解决**: 使用包含必要构建工具的自定义Docker镜像

### 编程方式使用

```python
from pathlib import Path
from sweagent.agent.mas.harmony_coordinator import HarmonyCoordinator
from sweagent.environment.repo import LocalRepository
from sweagent.environment.swe_env import EnvironmentConfig, SWEEnv

# 创建环境
repo = LocalRepository(repo_name="my_repo", path="/path/to/repo")
env = SWEEnv(EnvironmentConfig(repo=repo, deployment={"type": "docker"}))

# 创建协调器
coordinator = HarmonyCoordinator.from_config_files(
    env=env,
    topology_config_path=Path("config/agents/topology_agent.yaml"),
    temporal_config_path=Path("config/agents/temporal_agent.yaml"),
    review_config_path=Path("config/agents/review_agent.yaml"),
    contract_config_path=Path("config/agents/contract_agent.yaml"),
)

# 运行
patch = coordinator.run(issue_description="warning: ...", task_id="TASK-001")
print(patch)
```

### 进一步阅读

- 完整文档: `docs/harmony_mas_guide.md`
- 设计文档: `docs/plan.md`
- 原RCA/Patch系统: `sweagent/agent/mas/coordinator.py`

### 下一步

1. 尝试在测试仓库上运行系统
2. 根据需要自定义Agent配置
3. 扩展系统添加新的分析Agent
4. 集成到CI/CD流程中

## 贡献

欢迎贡献改进！请遵循以下步骤：

1. Fork项目
2. 创建特性分支
3. 提交更改
4. 创建Pull Request

## 联系方式

如有问题或建议，请通过以下方式联系：
- 提交Issue到GitHub仓库
- 查看文档: `docs/harmony_mas_guide.md`
