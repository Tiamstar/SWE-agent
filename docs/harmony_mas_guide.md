# Harmony Multi-Agent System (MAS) Guide

## Overview

The Harmony Multi-Agent System is a state-machine-based coordinator for fixing HarmonyOS repository-level warnings in C/C++ code. It orchestrates multiple specialized agents to analyze, generate, and verify patches in a systematic workflow.

## Architecture

### State Machine Workflow

```
INITIALIZED → ANALYSIS_TOPOLOGY → ANALYSIS_HISTORY →
PATCH_GENERATION → VERIFICATION_REVIEW → FINALIZING → FINISHED
                                  ↑                    ↓
                                  └────────────────────┘
                                    (iteration loop)
```

### Components

1. **HarmonyCoordinator** (`sweagent/agent/mas/harmony_coordinator.py`)
   - Central orchestrator implementing state machine logic
   - Manages shared state and agent dispatch
   - Handles iteration loops for failed patches

2. **SharedState** (`sweagent/agent/mas/shared_state.py`)
   - Single source of truth for workflow state
   - Stores insights from all agents
   - Tracks candidate patches and verification results

3. **Specialized Agents**:
   - **Topology Agent**: Analyzes code structure and dependencies
   - **Temporal Agent**: Analyzes git history and change patterns
   - **Review Agent**: Verifies patches compile successfully
   - **Contract Agent**: Verifies API contracts and assesses risk

## Usage

### Basic Usage

```bash
python tools/run_harmony_mas.py \
    --repo_path /path/to/harmonyos/repo \
    --issue "src/foundation/ace/adapter.cpp:142: warning: Potential null pointer dereference"
```

### Advanced Options

```bash
python tools/run_harmony_mas.py \
    --repo_path /path/to/repo \
    --issue "warning description" \
    --task_id CUSTOM-TASK-001 \
    --output_dir ./my_output \
    --max_iterations 5 \
    --image python:3.11
```

### Parameters

- `--repo_path`: Path to local repository (required)
- `--issue`: Warning/issue description to fix (required)
- `--task_id`: Optional task identifier (default: auto-generated)
- `--output_dir`: Output directory for trajectories (default: auto-generated)
- `--max_iterations`: Max iterations for patch refinement (default: 3)
- `--image`: Docker image to use (default: python:3.11)

## Workflow Details

### Stage 1: Topology Analysis

**Agent**: Topology Agent
**Purpose**: Understand code structure and dependencies
**Output**: JSON with:
- Target file and affected modules
- GN build dependencies
- Include relationships
- Criticality score (0.0-1.0)

**Tools Used**:
- `inspect_file_topology`
- `verify_func_signature`
- `find_upstream_callers`

### Stage 2: History Analysis

**Agent**: Temporal Agent
**Purpose**: Understand when and why the issue appeared
**Output**: JSON with:
- Blamed commit and author
- Co-changing files
- Change pattern summary
- Potential cause hypothesis

**Tools Used**:
- `git blame`
- `git log`
- `view_file_changelog`
- `search_historical_intent`

### Stage 3: Patch Generation

**Executor**: Coordinator (LLM-driven)
**Purpose**: Generate 1-3 candidate patches
**Input**: Accumulated insights from Topology + Temporal agents
**Output**: CandidatePatch objects with diff content

**Process**:
1. Synthesize insights from previous stages
2. Use LLM to generate patches addressing the warning
3. Consider previous violations if this is a retry iteration

### Stage 4: Verification & Review

**Agents**: Review Agent + Contract Agent
**Purpose**: Verify patches are safe and functional

**Review Agent**:
- Applies patch to repository
- Attempts compilation
- Returns: COMPILE_SUCCESS, COMPILE_FAILED, or APPLY_FAILED

**Contract Agent**:
- Checks for API contract violations (ABI breaks)
- Analyzes side effects (memory safety, concurrency)
- Calculates risk score (0.0-1.0)
- Returns: is_safe (True if risk < 0.5)

**Iteration Logic**:
- If any patch is SAFE → proceed to FINALIZING
- If all patches are UNSAFE → retry (up to max_iterations)
- If max iterations reached → proceed with best available patch

### Stage 5: Finalizing

**Executor**: Coordinator
**Purpose**: Select best patch and prepare final output

**Selection Criteria**:
1. COMPILE_SUCCESS patches only
2. Among compiled patches, prefer SAFE ones
3. Among safe patches, prefer lowest risk_score

### Stage 6: Finished

**Output**: Final patch diff ready for application

## Output Structure

After execution, the output directory contains:

```
trajectories/harmony_mas_<timestamp>/
├── state_<task_id>.json          # Complete shared state object
├── topology/
│   └── <task_id>/
│       └── <task_id>_topology.traj
├── temporal/
│   └── <task_id>/
│       └── <task_id>_temporal.traj
├── review/
│   └── <task_id>/
│       └── <task_id>_review.traj
└── contract/
    └── <task_id>/
        └── <task_id>_contract.traj
```

### Shared State Object

The `state_<task_id>.json` file contains:

```json
{
  "task_id": "AUTOFIX-20251216-001",
  "current_stage": "FINISHED",
  "initial_requirement": "Original warning description",
  "context_insights": {
    "topology": { /* TopologyInsight */ },
    "history": { /* HistoryInsight */ }
  },
  "candidate_patches": [
    {
      "id": "patch_1",
      "diff_content": "...",
      "build_status": "COMPILE_SUCCESS",
      "review_status": "SAFE",
      "review_risk_score": 0.15
    }
  ],
  "final_patch": {
    "id": "patch_final",
    "diff_content": "...",
    "description": "...",
    "verification_summary": "..."
  },
  "metadata": {
    "created_at": "2025-12-16T10:00:00",
    "patch_iteration": 1
  }
}
```

## Agent Configuration

### Customizing Agents

Agent configurations are located in `config/agents/`:
- `topology_agent.yaml`
- `temporal_agent.yaml`
- `review_agent.yaml`
- `contract_agent.yaml`

Each configuration defines:
- **System template**: Agent role and instructions
- **Tools**: Available tool bundles (harmony_graph, registry, etc.)
- **Model**: LLM model name and parameters
- **Execution limits**: Timeout, cost limit, max requeries

### Example: Modifying Risk Threshold

To make the Contract Agent more/less strict, edit `contract_agent.yaml`:

```yaml
templates:
  system_template: |
    ...
    - is_safe = True if risk_score < 0.3, else False  # More strict (was 0.5)
    ...
```

## Integration with Existing Code

### Using Harmony MAS Programmatically

```python
from pathlib import Path
from sweagent.agent.mas.harmony_coordinator import HarmonyCoordinator
from sweagent.environment.repo import LocalRepository
from sweagent.environment.swe_env import EnvironmentConfig, SWEEnv

# Setup repository
repo = LocalRepository(repo_name="my_repo", path="/path/to/repo")
env_config = EnvironmentConfig(repo=repo, deployment={"type": "docker"})
env = SWEEnv(env_config)

# Create coordinator
coordinator = HarmonyCoordinator.from_config_files(
    env=env,
    topology_config_path=Path("config/agents/topology_agent.yaml"),
    temporal_config_path=Path("config/agents/temporal_agent.yaml"),
    review_config_path=Path("config/agents/review_agent.yaml"),
    contract_config_path=Path("config/agents/contract_agent.yaml"),
    max_iterations=3,
)

# Run workflow
final_patch = coordinator.run(
    issue_description="warning: potential null pointer dereference...",
    task_id="CUSTOM-001",
)

print(final_patch)
```

### Extending with New Agents

To add a new agent to the workflow:

1. **Create agent configuration** (`config/agents/my_agent.yaml`)
2. **Define insight data class** in `sweagent/agent/mas/shared_state.py`:
   ```python
   @dataclass
   class MyInsight:
       insight_type: str = "my_insight"
       # ... fields ...
   ```
3. **Add stage to WorkflowStage enum**:
   ```python
   class WorkflowStage(str, Enum):
       # ... existing stages ...
       MY_STAGE = "MY_STAGE"
   ```
4. **Implement stage handler** in `HarmonyCoordinator`:
   ```python
   def _stage_my_stage(self) -> None:
       result = self._run_agent(self.my_config, "my_agent", prompt)
       insight = self._extract_my_insight(result)
       self.state.context_insights["my_insight"] = insight.to_dict()
       self.state.update_stage(WorkflowStage.NEXT_STAGE)
   ```
5. **Update state machine** in `_execute_state_machine()`:
   ```python
   elif current == WorkflowStage.MY_STAGE:
       self._stage_my_stage()
   ```

## Comparison with Previous RCA/Patch System

| Feature | RCA/Patch System | Harmony MAS |
|---------|------------------|-------------|
| Agents | 2 (RCA, Patch) | 4+ (Topology, Temporal, Review, Contract) |
| Workflow | Linear handoff | State machine with iteration |
| State Management | Implicit (prompt injection) | Explicit (SharedState object) |
| Verification | Optional | Mandatory (build + contract) |
| Iteration | No retry mechanism | Automatic retry on failures |
| Output Format | Unstructured | Structured JSON |
| Risk Assessment | None | Quantitative (0.0-1.0 risk score) |

## Best Practices

1. **Warning Descriptions**: Provide complete warning text with file path and line numbers
2. **Repository State**: Ensure repository is in a clean state (no uncommitted changes)
3. **Build System**: For complex projects, ensure build tools (gn, ninja, make) are available in the Docker image
4. **Iteration Limit**: Set `max_iterations` based on expected complexity (3-5 is typical)
5. **Tool Bundles**: Ensure harmony_graph tools are properly configured for your codebase

## Troubleshooting

### Issue: Agent returns unstructured output

**Cause**: Agent didn't follow JSON output format
**Solution**: Check agent's system template emphasizes "ONLY return JSON via submit"

### Issue: Patches fail verification repeatedly

**Cause**: Complex codebase or insufficient context
**Solution**:
- Increase `max_iterations`
- Provide more detailed warning description
- Check if harmony_graph tools are working correctly

### Issue: Environment setup fails

**Cause**: Missing dependencies in Docker image
**Solution**: Use a custom image with required build tools:
```bash
--image my-custom-image:latest
```

### Issue: State file shows ERROR stage

**Cause**: Unhandled exception in workflow
**Solution**: Check the exception in `metadata.error` field and agent trajectory files

## Future Enhancements

Potential improvements to the Harmony MAS:

1. **Parallel Agent Execution**: Run Topology + Temporal agents concurrently
2. **Advanced Patch Generation**: Use specialized patch generation agent instead of coordinator
3. **Test Suite Integration**: Add test execution agent for runtime verification
4. **Incremental Analysis**: Cache topology/history results across runs
5. **Multi-Patch Ranking**: Generate and rank multiple patches simultaneously
6. **Human-in-the-Loop**: Allow manual approval before applying patches

## References

- Design document: `docs/plan.md`
- Source code: `sweagent/agent/mas/`
- Agent configs: `config/agents/`
- Demo script: `tools/run_harmony_mas.py`
