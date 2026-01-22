# Harmony MAS Auto-Discovery Mode - Implementation Guide

## 📋 Overview

This guide explains how to integrate auto-discovery mode into the Harmony MAS system.

**What's New:**
- **Auto-Discovery Mode**: Automatically scan repo with cppcheck → LLM selects most critical warning → Fix it
- **Two Entry Points**:
  - `run()` - Original manual mode (user provides issue description)
  - `run_auto_discovery()` - New auto mode (system discovers and selects issue)

## 📁 Files Created

1. **sweagent/agent/mas/shared_state.py** ✅ MODIFIED
   - Added `WarningItem` dataclass
   - Added `WorkflowStage.WARNING_DISCOVERY` and `WorkflowStage.WARNING_TRIAGE`
   - Added `discovered_warnings` and `selected_warning` fields to `SharedState`

2. **sweagent/agent/mas/warning_scanner.py** ✅ CREATED
   - `WarningScanner` class for executing cppcheck scans
   - Parses cppcheck output into `WarningItem` objects

3. **sweagent/agent/mas/coordinator_autodiscovery_methods.py** ✅ CREATED
   - Contains 6 new/modified methods to integrate into `harmony_coordinator.py`

4. **tools/run_auto_discovery.py** ✅ CREATED
   - New entry script for auto-discovery mode

## 🔧 Integration Steps

### Step 1: Update harmony_coordinator.py imports

The imports have already been updated in the file (lines 1-51):
- Added `WarningItem` import
- Added `WarningScanner` import

### Step 2: Add triage_llm_config to __init__

Already added (lines 152-158):
```python
# Initialize LLM client for warning triage
self.triage_llm_config = {
    "model": patch_generator_config.model.name,
    "api_base": patch_generator_config.model.api_base,
    "api_key": patch_generator_config.model.api_key,
    "temperature": 0.0,
}
```

### Step 3: Add new methods to HarmonyCoordinator class

Now we need to integrate the methods from `coordinator_autodiscovery_methods.py`.

**Location guide:**
- `run_auto_discovery()` → Insert after `run()` method (around line 326)
- `_execute_state_machine()` → Replace existing (around line 327)
- `_stage_initialized()` → Replace existing (around line 362)
- `_stage_warning_discovery()` → Insert before `_stage_topology_analysis()` (around line 367)
- `_stage_warning_triage()` → Insert after `_stage_warning_discovery()`
- `_triage_warnings_with_llm()` → Insert before `_build_topology_prompt()` (around line 602)

## 🚀 Usage

### Auto-Discovery Mode (New)

```bash
python tools/run_auto_discovery.py \
    --repo_path /workspaces/SWE-agent/tcpdump \
    --source_dirs src lib \
    --max_warnings 200
```

**What it does:**
1. Scans repository with cppcheck
2. Finds up to 200 warnings
3. Calls LLM to select the most critical one
4. Executes full repair workflow for that warning

### Manual Mode (Original)

```bash
python tools/run_harmony_mas.py \
    --repo_path /workspaces/SWE-agent/tcpdump \
    --issue "print-ripng.c:142: warning: Potential null pointer dereference"
```

**What it does:**
1. Takes user-provided issue description
2. Executes full repair workflow for that specific issue

## 📊 Workflow Comparison

### Auto-Discovery Flow
```
INITIALIZED
    ↓
WARNING_DISCOVERY (cppcheck scan)
    ↓
WARNING_TRIAGE (LLM selects 1 warning)
    ↓
ANALYSIS_TOPOLOGY
    ↓
ANALYSIS_HISTORY
    ↓
PATCH_GENERATION
    ↓
VERIFICATION
    ↓
FINALIZING
    ↓
FINISHED
```

### Manual Flow (Original)
```
INITIALIZED
    ↓
ANALYSIS_TOPOLOGY
    ↓
ANALYSIS_HISTORY
    ↓
PATCH_GENERATION
    ↓
VERIFICATION
    ↓
FINALIZING
    ↓
FINISHED
```

## 🔍 Key Design Decisions

### 1. **Warning Triage in Coordinator (Not Separate Agent)**
   - **Why**: Single LLM call, no need for sub-agent overhead
   - **How**: Direct `litellm.completion()` call in `_triage_warnings_with_llm()`
   - **Benefit**: Faster, simpler, easier to maintain

### 2. **Reuse Existing Agent Infrastructure**
   - **What**: Once warning is selected, uses same agents (topology, temporal, patch_generator, verification)
   - **Why**: Consistency, no code duplication
   - **How**: `_stage_initialized()` routes to appropriate first stage based on mode

### 3. **Shared State Extensions**
   - **Added**: `discovered_warnings`, `selected_warning`
   - **Why**: Maintains single source of truth
   - **Benefit**: Full audit trail of discovery → selection → repair

## 🧪 Testing

### Test Auto-Discovery Mode

```bash
# Test with tcpdump repo
python tools/run_auto_discovery.py \
    --repo_path /workspaces/SWE-agent/tcpdump \
    --max_warnings 50

# Expected output:
# 1. "Scanning directories: src, lib, include"
# 2. "Discovered N warnings"
# 3. "Selected warning: warning_042"
# 4. Standard repair workflow output
# 5. Final patch
```

### Test Manual Mode (Should Still Work)

```bash
python tools/run_harmony_mas.py \
    --repo_path /workspaces/SWE-agent/tcpdump \
    --issue "test issue"

# Should work exactly as before
```

## 📝 Implementation Checklist

- [x] Extend SharedState with WarningItem
- [x] Create WarningScanner module
- [x] Write auto-discovery methods
- [x] Create run_auto_discovery.py entry script
- [ ] **Integrate methods into harmony_coordinator.py** ← NEXT STEP
- [ ] Test auto-discovery mode
- [ ] Test backward compatibility with manual mode
- [ ] Update documentation

## 🐛 Troubleshooting

### "cppcheck not found"
- Install cppcheck in Docker image: `apt-get install cppcheck`
- Or use custom image with cppcheck pre-installed

### "LLM triage failed"
- Check API key: `$QWEN_API_KEY`
- Check API base URL in model config
- System falls back to first warning if LLM fails

### "No warnings discovered"
- Check source directories exist: `ls -la src/`
- Try manual scan: `cppcheck src/ 2>&1 | head -20`
- Adjust cppcheck command in `WarningScanner._build_cppcheck_command()`

## 📚 Next Steps

After integration:
1. Test both modes thoroughly
2. Consider adding more triage criteria (frequency, file patterns)
3. Optionally: Add support for batch repair (fix multiple warnings)
4. Optionally: Add warning deduplication logic

## 🎯 Quick Start for Integration

Run this to see the methods that need to be integrated:

```bash
cat sweagent/agent/mas/coordinator_autodiscovery_methods.py | grep -E "^def |^# METHOD"
```

Then follow the "Location guide" in Step 3 above to insert each method.
