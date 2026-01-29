# Verification Agent Redesign Plan

## Current Issues

1. **Sequential verification**: Patches are verified one-by-one, not compared against each other
2. **Missing comprehensive evaluation**: Lacks interface constraint and type consistency checks
3. **No change propagation analysis**: Doesn't quantify risks through dependency graph
4. **No final validation**: After selection, doesn't verify if the warning is actually fixed
5. **State update issues**: Verification results not properly written to shared state

## New Workflow Design

### Phase 1: Batch Evaluation (All Patches)
```
Input: List of candidate patches
Output: Ranked patches with detailed risk assessment

For each patch:
  1. Interface Constraint Check:
     - Extract modified functions/APIs
     - Use verify_func_signature to check signature changes
     - Use find_upstream_callers to count impact scope

  2. Type Consistency Check:
     - Run cppcheck on modified code
     - Check for type mismatches, null pointer risks

  3. Change Propagation Analysis:
     - Use trace_downstream_impact to find affected components
     - Quantify propagation depth and breadth
     - Calculate risk score based on:
       * Number of downstream callers
       * Criticality of affected modules
       * Distance from change point

  4. Calculate Composite Score:
     - interface_safety_score (0.0-1.0)
     - type_safety_score (0.0-1.0)
     - propagation_risk_score (0.0-1.0)
     - overall_score = weighted average
```

### Phase 2: Selection
```
Select best patch based on:
  - Highest overall_score
  - Lowest propagation_risk_score
  - Fewest API breaking changes
```

### Phase 3: Validation
```
For selected patch:
  1. Apply patch to temporary workspace
  2. Run targeted cppcheck command:
     - Only check the specific file and line
     - Verify original warning no longer appears
  3. If validation fails:
     - Mark patch as invalid
     - Rollback changes
     - Select next best patch and retry
  4. If validation succeeds:
     - Return patch with validation proof
```

## Tool Requirements

### Existing Tools to Use:
- `verify_func_signature` - Check API signature changes
- `find_upstream_callers` - Count impact scope
- `trace_downstream_impact` - Analyze propagation paths
- `cppcheck` - Static analysis and validation

### New Helper Tool Needed:
- `verify_warning_fixed.sh` - Apply patch and check if specific warning is resolved

## Prompt Design Strategy

### System Template Changes:
1. Accept multiple patches as input (not single patch)
2. Emphasize batch evaluation before selection
3. Add explicit interface checking phase
4. Add explicit propagation analysis phase
5. Add final validation phase with rollback logic

### Output Format:
```json
{
  "evaluation_results": [
    {
      "patch_id": "patch_1",
      "interface_check": {
        "api_changes": ["func_foo signature changed"],
        "upstream_callers_count": 5,
        "breaking_changes": false,
        "safety_score": 0.9
      },
      "type_check": {
        "cppcheck_errors": [],
        "type_mismatches": [],
        "safety_score": 1.0
      },
      "propagation_analysis": {
        "downstream_components": ["module_a", "module_b"],
        "propagation_depth": 2,
        "affected_files_count": 8,
        "risk_score": 0.3
      },
      "overall_score": 0.85
    },
    ...
  ],
  "selected_patch_id": "patch_2",
  "validation_result": {
    "warning_fixed": true,
    "validation_command": "cppcheck --enable=warning src/foo.c:142",
    "validation_output": "No warnings found"
  }
}
```

## Implementation Steps

1. **Create helper tool**: `tools/verification_helpers/verify_warning_fixed.sh`
2. **Update verification_agent.yaml**: New system prompt with batch evaluation workflow
3. **Modify coordinator**:
   - Change `_stage_verification_review()` to send all patches at once
   - Update `_verify_patch()` to handle batch results
   - Add rollback logic for failed validations
4. **Update shared_state.py**: Add batch evaluation result structures
5. **Fix state update**: Ensure verification results are properly saved

## Risk Mitigation

- If tools fail (harmony_graph unavailable): Graceful fallback to basic static analysis
- If no patch passes validation: Return to patch generation with detailed feedback
- Timeout protection: Set max evaluation time per patch (30s)
