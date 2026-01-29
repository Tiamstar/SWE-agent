"""
Harmony Coordinator - Auto-Discovery Extension

This file contains the new methods to be added to harmony_coordinator.py
for auto-discovery mode support.

Methods to add:
1. run_auto_discovery() - New entry point for auto mode
2. _execute_state_machine() - Modified to handle new stages
3. _stage_initialized() - Modified to route to WARNING_DISCOVERY in auto mode
4. _stage_warning_discovery() - NEW: Execute cppcheck scan
5. _stage_warning_triage() - NEW: LLM selects most critical warning
6. _triage_warnings_with_llm() - NEW: Direct LLM API call for triage

Integration Instructions:
- Insert run_auto_discovery() after the existing run() method (line ~326)
- Replace _execute_state_machine() with the modified version
- Replace _stage_initialized() with the modified version
- Insert _stage_warning_discovery() and _stage_warning_triage() before _stage_topology_analysis()
- Insert _triage_warnings_with_llm() as a helper method
"""

# ============================================================================
# METHOD 1: run_auto_discovery() - NEW ENTRY POINT
# Insert after run() method (line ~326)
# ============================================================================

def run_auto_discovery(
    self,
    source_dirs: list[str] | None = None,
    max_warnings: int = 500,
    task_id: str | None = None,
) -> str:
    """Execute auto-discovery mode: scan repo -> select warning -> fix.

    This method implements the auto-discovery workflow:
    1. WARNING_DISCOVERY: cppcheck scan
    2. WARNING_TRIAGE: LLM selects most critical warning
    3-N: Standard repair workflow

    Args:
        source_dirs: Directories to scan (None = auto-detect)
        max_warnings: Maximum warnings to collect from scan
        task_id: Optional task identifier

    Returns:
        Final patch as string
    """
    # Initialize shared state
    if task_id is None:
        task_id = f"AUTODISCOVERY-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    self.state = SharedState(
        task_id=task_id,
        initial_requirement="",  # Will be set after warning selection
    )

    logger.info("=" * 70)
    logger.info(f"Starting Auto-Discovery Mode: {task_id}")
    logger.info("=" * 70)

    try:
        # Initialize environment
        self._initialize_environment()
        self.state.update_stage(WorkflowStage.INITIALIZED)

        # Mark this as auto-discovery mode
        self.state.metadata["mode"] = "auto-discovery"
        self.state.metadata["max_warnings"] = max_warnings
        self.state.metadata["source_dirs"] = source_dirs or "auto-detect"

        self._save_state()

        # Transition to WARNING_DISCOVERY
        self.state.update_stage(WorkflowStage.WARNING_DISCOVERY)

        # Execute state machine (will go through WARNING_DISCOVERY -> WARNING_TRIAGE -> ...)
        self._execute_state_machine()

        # Extract final result
        if self.state.final_patch:
            logger.info("✓ Auto-discovery workflow completed successfully")
            return self.state.final_patch.diff_content
        else:
            logger.warning("Workflow completed but no final patch generated")
            return "ERROR: No final patch generated"

    except Exception as e:
        logger.exception(f"Auto-discovery workflow failed: {e}")
        self.state.update_stage(WorkflowStage.ERROR)
        self.state.metadata["error"] = str(e)
        self._save_state()
        return f"ERROR: {e}"

    finally:
        # Close environment
        logger.info("Cleaning up environment")
        try:
            self.env.close()
        except Exception as e:
            logger.warning(f"Failed to close env: {e}")


# ============================================================================
# METHOD 2: _execute_state_machine() - MODIFIED VERSION
# Replace existing version (line ~327)
# ============================================================================

def _execute_state_machine(self) -> None:
    """Execute the state machine workflow.

    This is the core orchestration logic that transitions through stages.
    Handles both auto-discovery and manual modes.
    """
    while self.state.current_stage != WorkflowStage.FINISHED:
        current = self.state.current_stage

        logger.info(f"\n{'=' * 70}")
        logger.info(f"Current Stage: {current.value}")
        logger.info(f"{'=' * 70}")

        if current == WorkflowStage.INITIALIZED:
            self._stage_initialized()
        elif current == WorkflowStage.WARNING_DISCOVERY:
            self._stage_warning_discovery()
        elif current == WorkflowStage.WARNING_TRIAGE:
            self._stage_warning_triage()
        elif current == WorkflowStage.ANALYSIS_TOPOLOGY:
            self._stage_topology_analysis()
        elif current == WorkflowStage.ANALYSIS_HISTORY:
            self._stage_history_analysis()
        elif current == WorkflowStage.PATCH_GENERATION:
            self._stage_patch_generation()
        elif current == WorkflowStage.VERIFICATION:
            self._stage_verification_review()
        elif current == WorkflowStage.FINALIZING:
            self._stage_finalizing()
        elif current == WorkflowStage.ERROR:
            logger.error("Entered ERROR state, aborting workflow")
            break
        else:
            logger.error(f"Unknown stage: {current}")
            self.state.update_stage(WorkflowStage.ERROR)
            break

        # Save state after each stage
        self._save_state()


# ============================================================================
# METHOD 3: _stage_initialized() - MODIFIED VERSION
# Replace existing version (line ~362)
# ============================================================================

def _stage_initialized(self) -> None:
    """INITIALIZED stage: Route to next stage based on mode."""
    mode = self.state.metadata.get("mode", "manual")

    if mode == "auto-discovery":
        logger.info("Stage: INITIALIZED -> WARNING_DISCOVERY (auto-discovery mode)")
        self.state.update_stage(WorkflowStage.WARNING_DISCOVERY)
    else:
        logger.info("Stage: INITIALIZED -> ANALYSIS_TOPOLOGY (manual mode)")
        self.state.update_stage(WorkflowStage.ANALYSIS_TOPOLOGY)


# ============================================================================
# METHOD 4: _stage_warning_discovery() - NEW
# Insert before _stage_topology_analysis()
# ============================================================================

def _stage_warning_discovery(self) -> None:
    """WARNING_DISCOVERY stage: Execute cppcheck scan."""
    logger.info("Running cppcheck repository scan...")

    # Get scan parameters from metadata
    source_dirs = self.state.metadata.get("source_dirs")
    if source_dirs == "auto-detect":
        source_dirs = None  # Let scanner auto-detect

    max_warnings = self.state.metadata.get("max_warnings", 500)

    # Create scanner and execute scan
    scanner = WarningScanner(self.env)
    warnings = scanner.scan_repository(
        source_dirs=source_dirs,
        max_warnings=max_warnings,
    )

    if not warnings:
        logger.error("No warnings discovered, cannot proceed")
        self.state.update_stage(WorkflowStage.ERROR)
        self.state.metadata["error"] = "No warnings found by cppcheck scan"
        return

    # Save warnings to shared state
    self.state.discovered_warnings = warnings
    self.state.metadata["total_warnings_found"] = len(warnings)

    logger.info(f"✓ Discovered {len(warnings)} warnings")
    logger.info(f"  Top 5 warnings:")
    for i, w in enumerate(warnings[:5], 1):
        logger.info(f"    {i}. {w.file_path}:{w.line_number} [{w.severity}] {w.message[:60]}...")

    # Transition to triage
    self.state.update_stage(WorkflowStage.WARNING_TRIAGE)


# ============================================================================
# METHOD 5: _stage_warning_triage() - NEW
# Insert after _stage_warning_discovery()
# ============================================================================

def _stage_warning_triage(self) -> None:
    """WARNING_TRIAGE stage: LLM selects most critical warning."""
    logger.info("Analyzing warnings with LLM to select most critical one...")

    if not self.state.discovered_warnings:
        logger.error("No warnings available for triage")
        self.state.update_stage(WorkflowStage.ERROR)
        return

    # Call LLM for triage
    selected_warning = self._triage_warnings_with_llm(self.state.discovered_warnings)

    if not selected_warning:
        logger.error("LLM triage failed to select a warning")
        self.state.update_stage(WorkflowStage.ERROR)
        return

    # Set selected warning in state
    self.state.selected_warning = selected_warning

    # Convert warning to issue description for downstream agents
    self.state.initial_requirement = (
        f"{selected_warning.file_path}:{selected_warning.line_number}: "
        f"{selected_warning.severity}: {selected_warning.message}\n\n"
        f"Priority Score: {selected_warning.priority_score:.2f}\n"
        f"Selection Reason: {selected_warning.selection_reason}"
    )

    logger.info(f"✓ Selected warning: {selected_warning.id}")
    logger.info(f"  File: {selected_warning.file_path}:{selected_warning.line_number}")
    logger.info(f"  Message: {selected_warning.message}")
    logger.info(f"  Priority: {selected_warning.priority_score:.2f}")
    logger.info(f"  Reason: {selected_warning.selection_reason}")

    # Transition to topology analysis for selected warning
    self.state.update_stage(WorkflowStage.ANALYSIS_TOPOLOGY)


# ============================================================================
# METHOD 6: _triage_warnings_with_llm() - NEW HELPER
# Insert as a helper method (anywhere before _build_topology_prompt())
# ============================================================================

def _triage_warnings_with_llm(self, warnings: list[WarningItem]) -> WarningItem | None:
    """Use LLM to select the most critical warning from the list.

    Args:
        warnings: List of WarningItem objects

    Returns:
        Selected WarningItem with priority_score and selection_reason filled
    """
    # Build triage prompt
    warnings_summary = []
    for w in warnings[:100]:  # Limit to top 100 to avoid token limits
        warnings_summary.append({
            "id": w.id,
            "file": w.file_path,
            "line": w.line_number,
            "severity": w.severity,
            "message": w.message,
        })

    prompt = f"""Analyze these cppcheck warnings and select THE MOST CRITICAL ONE for immediate repair.

Total warnings found: {len(warnings)}
Showing top {min(100, len(warnings))} warnings:

{json.dumps(warnings_summary, indent=2)}

Your task:
1. Evaluate each warning based on:
   - Safety impact (crashes, data corruption, security)
   - File criticality (core modules > utilities > tests)
   - Repairability (clear fix vs complex refactoring)
   - Impact scope (frequently called vs rarely used)

2. Select exactly ONE warning that should be fixed first

3. Return JSON in this format:
{{
  "selected_warning_id": "warning_042",
  "priority_score": 0.95,
  "selection_reason": "Brief explanation why this is most critical (1-2 sentences)"
}}

Return ONLY the JSON, no other text."""

    # Call LLM API using litellm
    try:
        import litellm

        response = litellm.completion(
            model=self.triage_llm_config["model"],
            messages=[
                {"role": "system", "content": "You are an expert C/C++ code analyzer specializing in prioritizing bug fixes."},
                {"role": "user", "content": prompt},
            ],
            api_base=self.triage_llm_config.get("api_base"),
            api_key=self.triage_llm_config.get("api_key"),
            temperature=self.triage_llm_config.get("temperature", 0.0),
        )

        # Parse LLM response
        content = response.choices[0].message.content.strip()
        logger.debug(f"LLM triage response: {content}")

        # Extract JSON from response
        json_match = re.search(r'\{[\s\S]*\}', content)
        if not json_match:
            logger.error("LLM response does not contain valid JSON")
            return None

        result = json.loads(json_match.group())

        # Find the selected warning
        selected_id = result.get("selected_warning_id")
        if not selected_id:
            logger.error("LLM response missing selected_warning_id")
            return None

        for warning in warnings:
            if warning.id == selected_id:
                # Update warning with LLM-provided metadata
                warning.priority_score = result.get("priority_score", 0.5)
                warning.selection_reason = result.get("selection_reason", "Selected by LLM")
                return warning

        logger.error(f"Selected warning ID {selected_id} not found in warnings list")
        return None

    except Exception as e:
        logger.error(f"LLM triage failed: {e}")
        # Fallback: select first warning if LLM fails
        logger.warning("Falling back to first warning in list")
        first_warning = warnings[0]
        first_warning.priority_score = 0.5
        first_warning.selection_reason = "LLM triage failed, using first warning as fallback"
        return first_warning
