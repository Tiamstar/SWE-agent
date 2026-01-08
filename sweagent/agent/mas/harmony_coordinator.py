"""Harmony Multi-Agent System Coordinator.

This module implements the state-machine-based coordinator for HarmonyOS
repository-level warning repair. The coordinator orchestrates multiple
specialized agents following a defined workflow.

Workflow Stages:
    INITIALIZED -> ANALYSIS_TOPOLOGY -> ANALYSIS_HISTORY ->
    PATCH_GENERATION -> VERIFICATION -> FINALIZING -> FINISHED

Key Features:
    1. State Machine Logic: Deterministic stage transitions
    2. Shared State Management: Single source of truth
    3. Iterative Refinement: Retry loop for failed verifications
    4. Structured Communication: JSON-based agent outputs
"""

from __future__ import annotations

import json
import os
import hashlib
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from sweagent.agent.agents import DefaultAgent, DefaultAgentConfig
from sweagent.agent.problem_statement import TextProblemStatement
from sweagent.environment.swe_env import SWEEnv
from sweagent.types import AgentRunResult
from sweagent.utils.log import get_logger

from .shared_state import (
    CandidatePatch,
    FinalPatch,
    HistoryInsight,
    SharedState,
    TopologyInsight,
    VerificationInsight,
    WorkflowStage,
)

logger = get_logger("harmony-coordinator", emoji="🎯")


class HarmonyCoordinator:
    """State-Machine-Based Coordinator for Harmony MAS.

    This coordinator implements a deterministic workflow for fixing
    HarmonyOS C/C++ code warnings using multiple specialized agents.

    Architecture:
        - Hub-and-Spoke: Coordinator as central hub, agents as spokes
        - State Machine: Explicit stage transitions with validation
        - Shared State: All agents communicate through SharedState object
        - Iterative Refinement: Failed patches trigger re-generation

    Workflow:
        1. INITIALIZED: Set up shared environment
        2. ANALYSIS_TOPOLOGY: Analyze code structure and dependencies
        3. ANALYSIS_HISTORY: Analyze git history and change patterns
        4. PATCH_GENERATION: Generate 1-3 candidate patches
        5. VERIFICATION: Verify patches (build + contract check)
        6. FINALIZING: Select best patch and prepare final output
        7. FINISHED: Workflow complete
    """

    def __init__(
        self,
        env: SWEEnv,
        topology_config: DefaultAgentConfig,
        temporal_config: DefaultAgentConfig,
        patch_generator_config: DefaultAgentConfig,
        verification_config: DefaultAgentConfig,
        output_dir: Path | None = None,
        max_iterations: int = 3,
        num_candidate_patches: int = 3,
        coordinator_config_path: Path | None = None,
    ):
        """Initialize Harmony Coordinator.

        Args:
            env: Shared SWEEnv instance
            topology_config: Topology Analysis Agent configuration
            temporal_config: Temporal Awareness Agent configuration
            patch_generator_config: Patch Generator Agent configuration
            verification_config: Unified Verification Agent configuration (static + contract)
            output_dir: Output directory for trajectories
            max_iterations: Max iterations for patch refinement loop
            num_candidate_patches: Number of candidate patches to generate (1-5)
            coordinator_config_path: Path to coordinator configuration file (for prompts)
                If None, uses default prompts
        """
        self.env = env
        self.topology_config = topology_config
        self.temporal_config = temporal_config
        self.patch_generator_config = patch_generator_config
        self.verification_config = verification_config
        self.max_iterations = max_iterations
        self.num_candidate_patches = num_candidate_patches

        # Load coordinator configuration (prompts, etc.)
        self.coordinator_prompts = self._load_coordinator_config(coordinator_config_path)

        # Create output directory
        if output_dir is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.output_dir = Path("trajectories") / f"harmony_mas_{timestamp}"
        else:
            self.output_dir = output_dir

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Shared state will be created per run
        self.state: SharedState | None = None

        # Get project_id from environment or generate from repo path
        self.project_id = os.getenv("HARMONY_PROJECT_ID")
        if not self.project_id and hasattr(env.repo, 'path'):
            # Generate from repo path if not set
            repo_path = str(Path(env.repo.path).resolve())
            self.project_id = hashlib.sha256(repo_path.encode()).hexdigest()[:16]

        logger.info("=" * 70)
        logger.info("HarmonyCoordinator initialized")
        logger.info(f"  Shared env: {id(self.env)}")
        logger.info(f"  Project ID: {self.project_id}")
        logger.info(f"  Patch generator model: {patch_generator_config.model.name}")
        logger.info(f"  Output dir: {self.output_dir}")
        logger.info(f"  Max iterations: {max_iterations}")
        logger.info(f"  Candidate patches per iteration: {num_candidate_patches}")
        logger.info("=" * 70)

    def _load_coordinator_config(self, config_path: Path | None) -> dict[str, Any]:
        """Load coordinator configuration from YAML file.

        Args:
            config_path: Path to coordinator config file, or None for defaults

        Returns:
            Dictionary with configuration (prompts, settings, etc.)
        """
        if config_path and config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
            logger.info(f"Loaded coordinator config from: {config_path}")
            return config.get("prompts", {})
        else:
            logger.info("Using default coordinator prompts (no config file provided)")
            return {}

    def _ensure_project_indexed(self):
        """Ensure the current project is indexed in Neo4j.

        This method automatically indexes the project if not already indexed.
        It uses the harmony_graph indexing system to build a code graph.
        """
        if not self.project_id:
            logger.warning("No project_id available, skipping auto-indexing")
            return

        if not hasattr(self.env.repo, 'path'):
            logger.warning("No repo path available, skipping auto-indexing")
            return

        try:
            from tools.harmony_graph.lib.core import CodeGraphAgent

            agent = CodeGraphAgent()
            repo_path = str(Path(self.env.repo.path).resolve())

            if not agent.is_project_indexed(self.project_id):
                logger.info("=" * 70)
                logger.info("🔍 Project not indexed, building code graph...")
                logger.info(f"   Repository: {repo_path}")
                logger.info(f"   Project ID: {self.project_id}")
                logger.info("   This may take a few minutes for large projects...")
                logger.info("=" * 70)

                start_time = time.time()
                agent.index_project(repo_path, project_id=self.project_id, force_clean=False)
                elapsed = time.time() - start_time

                logger.info("=" * 70)
                logger.info(f"✅ Indexing completed in {elapsed:.1f} seconds")
                logger.info("   Subsequent runs will use cached data")
                logger.info("=" * 70)
            else:
                logger.info("✅ Project already indexed, using cached code graph")

            agent.close()
        except Exception as e:
            logger.warning(f"Auto-indexing failed (non-fatal): {e}")
            logger.warning("Agents may not have access to code graph data")

    @classmethod
    def from_config_files(
        cls,
        env: SWEEnv,
        topology_config_path: Path,
        temporal_config_path: Path,
        patch_generator_config_path: Path,
        verification_config_path: Path,
        coordinator_config_path: Path | None = None,
        output_dir: Path | None = None,
        max_iterations: int = 3,
        num_candidate_patches: int = 3,
    ) -> HarmonyCoordinator:
        """Create coordinator from YAML configuration files.

        Args:
            env: Shared SWEEnv instance
            topology_config_path: Path to Topology Agent config
            temporal_config_path: Path to Temporal Agent config
            patch_generator_config_path: Path to Patch Generator Agent config
            verification_config_path: Path to Verification Agent config (unified)
            coordinator_config_path: Path to Coordinator config (for prompts and settings)
            output_dir: Output directory
            max_iterations: Max refinement iterations
            num_candidate_patches: Number of candidate patches to generate

        Returns:
            HarmonyCoordinator instance
        """

        def load_config(path: Path) -> DefaultAgentConfig:
            with open(path) as f:
                data = yaml.safe_load(f)
            return DefaultAgentConfig(**data)

        return cls(
            env=env,
            topology_config=load_config(topology_config_path),
            temporal_config=load_config(temporal_config_path),
            patch_generator_config=load_config(patch_generator_config_path),
            verification_config=load_config(verification_config_path),
            coordinator_config_path=coordinator_config_path,
            output_dir=output_dir,
            max_iterations=max_iterations,
            num_candidate_patches=num_candidate_patches,
        )

    def run(self, issue_description: str, task_id: str | None = None) -> str:
        """Execute the complete Harmony MAS workflow.

        This method implements the state machine logic, transitioning through
        stages and invoking specialized agents at each step.

        Args:
            issue_description: HarmonyOS warning/issue to fix
            task_id: Optional task identifier

        Returns:
            Final patch as string
        """
        # Initialize shared state
        if task_id is None:
            task_id = f"AUTOFIX-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        self.state = SharedState(
            task_id=task_id,
            initial_requirement=issue_description,
        )

        logger.info("=" * 70)
        logger.info(f"Starting Harmony MAS Workflow: {task_id}")
        logger.info("=" * 70)

        try:
            # Initialize environment (includes indexing)
            self._initialize_environment()
            self.state.update_stage(WorkflowStage.INITIALIZED)
            self._save_state()

            # State machine execution
            self._execute_state_machine()

            # Extract final result
            if self.state.final_patch:
                logger.info("✓ Workflow completed successfully")
                return self.state.final_patch.diff_content
            else:
                logger.warning("Workflow completed but no final patch generated")
                return "ERROR: No final patch generated"

        except Exception as e:
            logger.exception(f"Workflow failed: {e}")
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

    def _execute_state_machine(self) -> None:
        """Execute the state machine workflow.

        This is the core orchestration logic that transitions through stages.
        """
        while self.state.current_stage != WorkflowStage.FINISHED:
            current = self.state.current_stage

            logger.info(f"\n{'=' * 70}")
            logger.info(f"Current Stage: {current.value}")
            logger.info(f"{'=' * 70}")

            if current == WorkflowStage.INITIALIZED:
                self._stage_initialized()
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

    def _stage_initialized(self) -> None:
        """INITIALIZED stage: Transition to topology analysis."""
        logger.info("Stage: INITIALIZED -> ANALYSIS_TOPOLOGY")
        self.state.update_stage(WorkflowStage.ANALYSIS_TOPOLOGY)

    def _stage_topology_analysis(self) -> None:
        """ANALYSIS_TOPOLOGY stage: Run Topology Agent."""
        logger.info("Running Topology Analysis Agent...")

        result = self._run_agent(
            config=self.topology_config,
            agent_name="topology",
            problem_statement=self._build_topology_prompt(),
        )

        # Extract structured insight
        insight = self._extract_topology_insight(result)
        self.state.add_topology_insight(insight)

        logger.info(f"✓ Topology analysis complete: {insight.summary}")
        self.state.update_stage(WorkflowStage.ANALYSIS_HISTORY)

    def _stage_history_analysis(self) -> None:
        """ANALYSIS_HISTORY stage: Run Temporal Agent."""
        logger.info("Running Temporal Awareness Agent...")

        result = self._run_agent(
            config=self.temporal_config,
            agent_name="temporal",
            problem_statement=self._build_temporal_prompt(),
        )

        # Extract structured insight
        insight = self._extract_history_insight(result)
        self.state.add_history_insight(insight)

        logger.info(f"✓ History analysis complete: {insight.change_pattern_summary}")
        self.state.update_stage(WorkflowStage.PATCH_GENERATION)

    def _stage_patch_generation(self) -> None:
        """PATCH_GENERATION stage: Generate patches using PatchGeneratorAgent.

        This stage handles both initial generation and retries after verification failures.
        It checks retry count to determine if we should continue or finalize.
        """
        retry_count = self.state.get_retry_count()

        # Check if we've exceeded max iterations
        if retry_count >= self.max_iterations:
            logger.warning(f"Max iterations ({self.max_iterations}) reached, proceeding to finalization")
            self.state.update_stage(WorkflowStage.FINALIZING)
            return

        # Log iteration info
        if retry_count == 0:
            logger.info(f"Generating {self.num_candidate_patches} initial candidate patches...")
        else:
            logger.info(f"Retry patch generation (iteration {retry_count + 1}/{self.max_iterations})...")

        # Build comprehensive context from insights
        problem_statement = self._build_patch_generation_prompt()

        # Run PatchGeneratorAgent
        result = self._run_agent(
            config=self.patch_generator_config,
            agent_name="patch_generator",
            problem_statement=problem_statement,
        )

        # Extract patches from agent submission
        patches = self._extract_patches_from_result(result)

        # Add each patch to state with appropriate ID
        for i, patch_content in enumerate(patches, 1):
            if retry_count == 0:
                patch_id = f"patch_{i}"
                updated_by = "PatchGeneratorAgent"
            else:
                patch_id = f"patch_retry{retry_count}_{i}"
                updated_by = f"PatchGeneratorAgent (retry {retry_count})"

            candidate = CandidatePatch(
                id=patch_id,
                diff_content=patch_content,
                last_updated_by=updated_by,
            )
            self.state.add_candidate_patch(candidate)

        logger.info(f"✓ Generated {len(patches)} candidate patch(es)")
        self.state.update_stage(WorkflowStage.VERIFICATION)

    def _stage_verification_review(self) -> None:
        """VERIFICATION stage: Verify patches with unified Verification agent."""
        logger.info("Verifying candidate patches...")

        # Verify each candidate patch
        for patch in self.state.candidate_patches:
            # Check if already verified (using new field or legacy field)
            if patch.verification_status != "PENDING" or patch.build_status not in ["PENDING", ""]:
                continue  # Already verified

            logger.info(f"Verifying patch: {patch.id}")

            # Run unified verification agent
            verification_insight = self._verify_patch(patch)

            # Update state with verification results
            self.state.update_patch_verification(patch.id, verification_insight)

            # Log results
            if verification_insight.is_safe:
                logger.info(f"✓ Patch {patch.id} is SAFE (quality: {verification_insight.quality_score:.2f}, risk: {verification_insight.risk_score:.2f})")
            else:
                logger.warning(f"✗ Patch {patch.id} is UNSAFE (quality: {verification_insight.quality_score:.2f}, risk: {verification_insight.risk_score:.2f})")

        # Check if any patches are safe
        safe_patches = [p for p in self.state.candidate_patches if p.verification_status == "SAFE" or p.review_status == "SAFE"]

        if safe_patches:
            logger.info(f"✓ Found {len(safe_patches)} safe patch(es)")
            self.state.update_stage(WorkflowStage.FINALIZING)
        else:
            logger.warning("No safe patches found, preparing for retry...")
            # Prepare for retry and go back to PATCH_GENERATION
            self.state.prepare_for_retry()
            self.state.update_stage(WorkflowStage.PATCH_GENERATION)

    def _stage_finalizing(self) -> None:
        """FINALIZING stage: Select best patch and finalize."""
        logger.info("Finalizing patch selection...")

        best_patch = self.state.get_best_candidate()

        if best_patch:
            final = FinalPatch(
                id="patch_final",
                diff_content=best_patch.diff_content,
                description=f"Selected from candidate {best_patch.id}",
                verification_summary=f"Build: {best_patch.build_status}, Review: {best_patch.review_status}, Risk: {best_patch.review_risk_score}",
            )
            self.state.set_final_patch(final)
            logger.info(f"✓ Final patch selected: {best_patch.id} (risk: {best_patch.review_risk_score})")
        else:
            logger.warning("No suitable candidate found, using fallback")
            final = FinalPatch(
                id="patch_final",
                diff_content="# No safe patch could be generated",
                description="Workflow completed but no safe patch was found",
                verification_summary="All candidates failed verification",
            )
            self.state.set_final_patch(final)

        self.state.update_stage(WorkflowStage.FINISHED)

    def _initialize_environment(self) -> None:
        """Initialize shared environment with tools and code indexing.

        This method:
        1. Starts the environment
        2. Installs all required tools from agent configs
        3. Ensures the project is indexed in Neo4j (once)
        """
        logger.info("Initializing shared environment...")
        self.env.start()

        # Install tools from all agent configs
        from sweagent.tools.tools import ToolHandler

        for config in [
            self.topology_config,
            self.temporal_config,
            self.patch_generator_config,
            self.verification_config,
        ]:
            tool_handler = ToolHandler(config.tools)
            tool_handler.install(self.env)

        logger.info("✓ Environment and tools initialized")

        # Ensure project is indexed (once per workflow)
        self._ensure_project_indexed()

    def _run_agent(
        self,
        config: DefaultAgentConfig,
        agent_name: str,
        problem_statement: str,
        timeout_seconds: int | None = None,
    ) -> AgentRunResult:
        """Run a specialized agent with timeout monitoring.

        Args:
            config: Agent configuration
            agent_name: Agent identifier (for output paths)
            problem_statement: Problem statement for the agent
            timeout_seconds: Expected max execution time in seconds (default: 300 for most agents)
                Topology/Temporal: 180s, Review/Contract: 240s, PatchGenerator: 360s

        Returns:
            AgentRunResult

        Note:
            This method monitors agent execution time and logs warnings if the agent
            exceeds the expected timeout. The agent will still complete, but the
            warning helps identify inefficient agents that need prompt improvements.
        """
        # Set default timeouts based on agent type
        if timeout_seconds is None:
            timeout_map = {
                "topology": 180,      # 3 minutes
                "temporal": 180,      # 3 minutes
                "review": 240,        # 4 minutes
                "contract": 240,      # 4 minutes
                "patch_generator": 360,  # 6 minutes
            }
            timeout_seconds = timeout_map.get(agent_name, 300)

        logger.info(f"Creating {agent_name} agent (timeout: {timeout_seconds}s)...")
        agent = DefaultAgent.from_config(config, injected_env=self.env)

        # Ensure independent history
        agent.history = []

        # Create problem statement
        ps = TextProblemStatement(
            id=f"{self.state.task_id}_{agent_name}",
            text=problem_statement,
        )

        # Run agent with time tracking
        output_dir = self.output_dir / agent_name / self.state.task_id
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Running {agent_name} agent...")
        start_time = time.time()

        try:
            result = agent.run(env=None, problem_statement=ps, output_dir=output_dir)
            elapsed_time = time.time() - start_time

            # Check if agent exceeded expected timeout
            if elapsed_time > timeout_seconds:
                logger.warning(
                    f"⚠️  {agent_name} agent exceeded expected timeout: "
                    f"{elapsed_time:.1f}s > {timeout_seconds}s "
                    f"(+{elapsed_time - timeout_seconds:.1f}s over)"
                )
                logger.warning(
                    f"Consider improving {agent_name} agent's system prompt for better efficiency"
                )
            else:
                logger.info(f"✓ {agent_name} agent completed in {elapsed_time:.1f}s")

            return result

        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(
                f"✗ {agent_name} agent failed after {elapsed_time:.1f}s: {e}"
            )
            raise

    def _build_topology_prompt(self) -> str:
        """Build prompt for Topology Agent."""
        # Use configured prompt template if available, otherwise use default
        template = self.coordinator_prompts.get("topology_analysis", """
ROLE: Harmony Topology Analysis Agent
Task: Analyze the code structure and dependencies for the following warning.

Warning Description:
{initial_requirement}

Your task:
1. Use harmony_graph tools to analyze file topology
2. Identify affected modules and dependencies
3. Return a structured JSON response with the following format:

{{
  "insight_type": "topology",
  "target_file": "path/to/file.c",
  "affected_module": ["module_name"],
  "gn_dependency_files": ["//build/config/module.gni"],
  "direct_includes": ["<header.h>", "\\"local.h\\""],
  "summary": "Brief summary of findings"
}}

Use the 'submit' command to return your JSON response.
""")
        return template.format(initial_requirement=self.state.initial_requirement)

    def _build_temporal_prompt(self) -> str:
        """Build prompt for Temporal Agent."""
        topology = self.state.context_insights.get("topology", {})
        target_file = topology.get("target_file", "")

        # Use configured prompt template if available, otherwise use default
        template = self.coordinator_prompts.get("temporal_analysis", """
ROLE: Harmony Temporal Awareness Agent
Task: Analyze git history and change patterns for the following warning.

Warning Description:
{initial_requirement}

Target File: {target_file}

Your task:
1. Use harmony_graph tools and git commands to analyze history
2. Identify blamed commits and co-changing files
3. Return a structured JSON response with the following format:

{{
  "insight_type": "history",
  "blamed_commit": "commit_hash",
  "blamed_author": "author_name",
  "co_changing_files": ["file1.c", "file2.h"],
  "change_pattern_summary": "Summary of change patterns",
  "potential_cause": "Potential root cause based on history"
}}

Use the 'submit' command to return your JSON response.
""")
        return template.format(
            initial_requirement=self.state.initial_requirement,
            target_file=target_file
        )

    def _build_patch_generation_prompt(self) -> str:
        """Build prompt for PatchGeneratorAgent with accumulated insights.

        Returns:
            Formatted prompt with context and requirements
        """
        topology = self.state.context_insights.get("topology", {})
        history = self.state.context_insights.get("history", {})

        # Get accumulated violations if this is a retry
        violations = self.state.get_accumulated_violations()
        violations_section = ""
        if violations:
            violations_template = self.coordinator_prompts.get("previous_violations_section", """

Previous Patch Violations (AVOID THESE):
{previous_violations}
""")
            violations_section = violations_template.format(
                previous_violations=json.dumps(violations, indent=2)
            )

        # Use configured prompt template if available, otherwise use default
        template = self.coordinator_prompts.get("patch_generation", """Generate {num_candidates} different candidate patches to fix the following warning.

CONTEXT
=======

Original Warning:
{initial_requirement}

Topology Analysis Results:
{topology_insights}

History Analysis Results:
{history_insights}

{previous_violations_section}

REQUIREMENTS
============
1. Generate {num_candidates} DIFFERENT approaches to fix the issue
2. Each patch should be a valid unified diff format
3. Patches should vary in approach (conservative, moderate, aggressive)
4. Return patches separated by "=== PATCH N ===" markers
5. Each patch must be complete and applicable

Use the 'submit' command to return your patches.
""")

        return template.format(
            num_candidates=self.num_candidate_patches,
            initial_requirement=self.state.initial_requirement,
            topology_insights=json.dumps(topology, indent=2),
            history_insights=json.dumps(history, indent=2),
            previous_violations_section=violations_section,
        )

    def _extract_mas_result(self, result: AgentRunResult) -> str | None:
        """Extract result from MAS agent using <<MAS_AGENT_RESULT>> markers.

        This method looks for the special MAS_AGENT_RESULT markers in the
        trajectory's observations. This is the preferred method for multi-agent
        communication as it doesn't rely on file system modifications.

        Args:
            result: Agent run result

        Returns:
            Extracted result content or None if not found
        """
        # Search through trajectory steps (most recent first)
        for step in reversed(result.trajectory):
            observation = step.get("observation", "")
            if "<<MAS_AGENT_RESULT>>" in observation:
                # Extract content between markers
                import re
                pattern = r'<<MAS_AGENT_RESULT>>\s*(.*?)\s*<<MAS_AGENT_RESULT>>'
                match = re.search(pattern, observation, re.DOTALL)
                if match:
                    content = match.group(1).strip()
                    logger.info(f"✓ Extracted MAS result ({len(content)} chars)")
                    return content
        return None

    def _extract_patches_from_result(self, result: AgentRunResult) -> list[str]:
        """Extract patch diffs from PatchGeneratorAgent result.

        This method implements a robust four-tier fallback strategy:
        1. Try to extract from MAS result markers (preferred for multi-agent)
        2. Try to extract from submission field (standard submit command output)
        3. If empty, extract from trajectory's last response (LLM-generated content)
        4. If still empty, create placeholder patch

        Args:
            result: Agent run result

        Returns:
            List of patch diff contents (1-N patches)
        """
        patches = []

        # TIER 1: Try to extract from MAS result markers (PREFERRED)
        mas_result = self._extract_mas_result(result)
        if mas_result:
            logger.info("Extracting patches from MAS result markers...")
            patches = self._parse_patches_from_text(mas_result)
            if patches:
                return patches[:self.num_candidate_patches]

        # TIER 2: Try to extract from submission field
        submission = result.info.get("submission") or ""
        if submission.strip():
            logger.info("Attempting to extract patches from submission field...")
            patches = self._parse_patches_from_text(submission)

        # TIER 3: If submission is empty, extract from trajectory
        if not patches:
            logger.warning("Submission field is empty, extracting from trajectory...")
            patches = self._extract_patches_from_trajectory(result.trajectory)

        # TIER 4: If still no patches, create placeholder
        if not patches:
            logger.error("No valid patches found in submission or trajectory, creating placeholder")
            patches = [self._create_placeholder_patch()]

        # Limit to requested number
        patches = patches[:self.num_candidate_patches]

        logger.info(f"✓ Extracted {len(patches)} patch(es) from PatchGeneratorAgent")
        return patches

    def _parse_patches_from_text(self, text: str) -> list[str]:
        """Parse patches from text content with improved robustness.

        Supports multiple formats:
        1. Patches separated by === PATCH N === markers (RECOMMENDED)
        2. Patches separated by markdown code blocks
        3. Single unified patch (all diff blocks together)
        4. Multiple diffs with intelligent grouping

        IMPORTANT: When a patch modifies multiple files, they should be kept together
        as a single patch. Use === PATCH N === markers to separate different patch alternatives.

        Args:
            text: Text content containing patches

        Returns:
            List of patch diff strings
        """
        patches = []

        # Strip markdown code blocks if present
        # Remove ```diff or ``` wrappers
        text = re.sub(r'```(?:diff)?\n', '', text)
        text = re.sub(r'\n```', '', text)

        # Method 1: Try to split by PATCH markers (PREFERRED)
        # Pattern matches: === PATCH 1 ===, ===PATCH 2===, === PATCH N ===
        patch_marker_pattern = r'(?:^|\n)===+\s*PATCH\s+\d+\s*===+(?:\n|$)'
        if re.search(patch_marker_pattern, text, re.MULTILINE):
            logger.info("Found === PATCH N === markers, splitting patches...")
            patch_blocks = re.split(patch_marker_pattern, text)
            for block in patch_blocks:
                block = block.strip()
                if block and self._is_valid_patch_content(block):
                    patches.append(block)

        # Method 2: If no markers, try intelligent grouping
        # Check if multiple diffs exist and whether they're part of same patch or different
        if not patches and text.count('diff --git') > 1:
            logger.info("Multiple diffs found without markers, applying intelligent grouping...")
            patches = self._group_diffs_intelligently(text)

        # Method 3: Treat entire content as single patch
        # This is a safe fallback that keeps multi-file patches intact
        if not patches:
            text = text.strip()
            if self._is_valid_patch_content(text):
                logger.info("Treating entire content as single patch")
                patches.append(text)

        return patches

    def _is_valid_patch_content(self, content: str) -> bool:
        """Check if content appears to be valid patch/diff content.

        Args:
            content: Text to validate

        Returns:
            True if content looks like a valid patch
        """
        if not content:
            return False

        # Must contain diff or patch markers
        has_diff_git = 'diff --git' in content
        has_unified_diff = '@@' in content
        has_traditional_diff = (content.count('\n---') > 0 and content.count('\n+++') > 0)

        return has_diff_git or has_unified_diff or has_traditional_diff

    def _group_diffs_intelligently(self, text: str) -> list[str]:
        """Intelligently group multiple diffs into patches.

        Uses heuristics to determine if multiple diffs belong together:
        - Consecutive diffs without blank lines → same patch
        - Diffs separated by significant blank lines → different patches
        - Diffs with explanatory text between them → different patches

        Args:
            text: Text containing multiple diffs

        Returns:
            List of grouped patches
        """
        patches = []

        # Split by diff --git lines
        diff_parts = re.split(r'(diff --git [^\n]+)', text)

        current_patch = []
        last_was_diff = False

        for i, part in enumerate(diff_parts):
            part = part.strip()
            if not part:
                continue

            # If this is a diff --git line
            if part.startswith('diff --git'):
                # Check what comes after (the actual diff content)
                if i + 1 < len(diff_parts):
                    next_part = diff_parts[i + 1].strip()

                    # If there's significant text between diffs (not just diff content)
                    # treat as separate patch
                    if current_patch and self._looks_like_separator(next_part):
                        # Save current patch and start new one
                        patches.append('\n'.join(current_patch))
                        current_patch = [part]
                    else:
                        # Add to current patch
                        current_patch.append(part)
                        last_was_diff = True
                else:
                    current_patch.append(part)
                    last_was_diff = True
            else:
                # This is diff content
                if last_was_diff or not current_patch:
                    current_patch.append(part)
                else:
                    # New explanatory text - might be new patch description
                    if self._looks_like_separator(part):
                        # Save current patch
                        if current_patch:
                            patches.append('\n'.join(current_patch))
                        current_patch = []
                    else:
                        current_patch.append(part)
                last_was_diff = False

        # Add remaining patch
        if current_patch:
            patches.append('\n'.join(current_patch))

        # If we ended up with only one group, just return the whole thing
        if len(patches) == 1:
            return [text.strip()]

        return patches

    def _looks_like_separator(self, text: str) -> bool:
        """Check if text looks like a separator between patches.

        Args:
            text: Text to check

        Returns:
            True if text appears to be patch separator
        """
        if not text:
            return False

        # Long blank sections
        if text.count('\n') > 5:
            return True

        # Contains phrases like "Alternative approach", "Second patch", etc.
        separator_phrases = [
            'alternative', 'another approach', 'second', 'third',
            'different', 'option', 'patch 2', 'patch 3'
        ]
        text_lower = text.lower()
        if any(phrase in text_lower for phrase in separator_phrases):
            return True

        return False

    def _extract_patches_from_trajectory(self, trajectory: list[dict]) -> list[str]:
        """Extract patches from trajectory history.

        This is a fallback method when submission field is empty.
        It searches through the last N steps of the trajectory for patch content.

        Args:
            trajectory: Agent trajectory (list of steps)

        Returns:
            List of patch diff strings
        """
        patches = []

        # Search through last 5 steps (most recent first)
        search_steps = min(5, len(trajectory))
        for i in range(len(trajectory) - 1, len(trajectory) - search_steps - 1, -1):
            if i < 0:
                break

            step = trajectory[i]

            # Check multiple possible locations for patch content
            candidates = [
                step.get("response", ""),
                step.get("thought", ""),
                step.get("action", ""),
            ]

            for candidate_text in candidates:
                if not candidate_text:
                    continue

                # Look for patch markers or diff content
                if "PATCH" in candidate_text or "diff --git" in candidate_text:
                    logger.info(f"Found patch content in trajectory step {i}")
                    extracted = self._parse_patches_from_text(candidate_text)
                    if extracted:
                        patches.extend(extracted)

            # If we found patches, stop searching
            if patches:
                break

        return patches

    def _extract_json_from_trajectory(self, trajectory: list[dict]) -> str:
        """Extract JSON content from trajectory history.

        This is a fallback method when submission field is empty.
        It searches through the last N steps for JSON-like content.

        Args:
            trajectory: Agent trajectory (list of steps)

        Returns:
            JSON string or empty string if not found
        """
        # Search through last 3 steps (most recent first)
        search_steps = min(3, len(trajectory))
        for i in range(len(trajectory) - 1, len(trajectory) - search_steps - 1, -1):
            if i < 0:
                break

            step = trajectory[i]

            # Check multiple possible locations
            candidates = [
                step.get("response", ""),
                step.get("thought", ""),
                step.get("action", ""),
            ]

            for candidate_text in candidates:
                if not candidate_text:
                    continue

                # Look for JSON-like content (objects with curly braces)
                if "{" in candidate_text and "}" in candidate_text:
                    # Try to extract a JSON object
                    json_match = re.search(r"\{[\s\S]*\}", candidate_text)
                    if json_match:
                        logger.info(f"Found JSON-like content in trajectory step {i}")
                        return json_match.group()

        return ""

    def _create_placeholder_patch(self) -> str:
        """Create a placeholder patch when agent fails.

        Returns:
            Placeholder patch content
        """
        return """diff --git a/file.c b/file.c
index 0000000..1111111 100644
--- a/file.c
+++ b/file.c
@@ -1,1 +1,2 @@
 // Original code
+// TODO: Fix based on analysis
// PatchGeneratorAgent failed, placeholder created
"""

    def _verify_patch(self, patch: CandidatePatch) -> VerificationInsight:
        """Verify patch with unified Verification Agent.

        Args:
            patch: Candidate patch to verify

        Returns:
            VerificationInsight with combined static analysis and contract check results
        """
        logger.info(f"Running unified verification on {patch.id}...")

        # Check if this is a placeholder patch
        if "PatchGeneratorAgent failed, placeholder created" in patch.diff_content:
            logger.warning(f"Skipping verification for placeholder patch {patch.id}")
            return VerificationInsight(
                patch_id=patch.id,
                is_safe=False,
                quality_score=0.0,
                risk_score=1.0,
                overall_score=0.0,
                static_analysis={"status": "CHECK_SKIPPED", "tool_used": "none"},
                contract_check={"api_changes_detected": False, "violation_list": []},
                recommendation="Placeholder patch cannot be verified",
            )

        # Build prompt for Verification Agent
        prompt = f"""Candidate Patch to Verify:

{patch.diff_content}

Perform comprehensive verification (static analysis + contract check).
"""

        try:
            # Run Verification Agent
            result = self._run_agent(
                config=self.verification_config,
                agent_name="verification",
                problem_statement=prompt,
            )

            # Extract VerificationInsight from result
            submission = result.info.get("submission") or ""

            # Try to parse JSON
            json_match = re.search(r'\{[\s\S]*\}', submission)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    return VerificationInsight.from_dict(data)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse JSON from verification agent")

            # Fallback: assume safe with medium confidence
            return VerificationInsight(
                patch_id=patch.id,
                is_safe=True,
                quality_score=0.7,
                risk_score=0.3,
                overall_score=0.7,
                static_analysis={"status": "CHECK_SKIPPED", "tool_used": "none"},
                contract_check={"api_changes_detected": False, "violation_list": []},
                recommendation="Verification agent did not return structured output, assuming safe",
            )

        except Exception as e:
            logger.error(f"Verification agent failed: {e}")
            return VerificationInsight(
                patch_id=patch.id,
                is_safe=True,
                quality_score=0.5,
                risk_score=0.5,
                overall_score=0.5,
                static_analysis={"status": "CHECK_SKIPPED", "tool_used": "none"},
                contract_check={"api_changes_detected": False, "violation_list": []},
                recommendation=f"Verification agent error: {str(e)}, assuming safe",
            )

    def _extract_topology_insight(self, result: AgentRunResult) -> TopologyInsight:
        """Extract structured TopologyInsight from agent result.

        This method implements a four-tier extraction strategy:
        1. Try to extract from MAS result markers (preferred)
        2. Try to parse structured JSON from submission
        3. If submission empty, try to parse from trajectory
        4. If parsing fails, extract key information from text
        5. As last resort, return minimal default insight

        Args:
            result: Agent run result

        Returns:
            TopologyInsight
        """
        # TIER 1: Try to extract from MAS result markers (PREFERRED)
        mas_result = self._extract_mas_result(result)
        submission = mas_result if mas_result else result.info.get("submission") or ""

        # If submission is empty, try trajectory
        if not submission.strip():
            logger.warning("Topology agent submission is empty, checking trajectory...")
            submission = self._extract_json_from_trajectory(result.trajectory)

        # Tier 1: Try to parse structured JSON
        json_match = re.search(r"\{[\s\S]*\}", submission)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return TopologyInsight.from_dict(data)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON from topology agent: {e}")

        # Tier 2: Fallback - extract information from text
        logger.info("Attempting to extract topology insights from unstructured text")

        # Try to extract target file
        target_file = None
        file_patterns = [
            r"target_file[\"']?\s*:\s*[\"']([^\"']+)[\"']",
            r"file:\s*([^\s,]+\.[ch](?:pp)?)",
            r"analyzing\s+(?:file\s+)?([^\s,]+\.[ch](?:pp)?)",
        ]
        for pattern in file_patterns:
            match = re.search(pattern, submission, re.IGNORECASE)
            if match:
                target_file = match.group(1)
                break

        # Try to extract includes
        includes = []
        include_pattern = r'#include\s+[<"]([^>"]+)[>"]'
        includes = re.findall(include_pattern, submission)
        if includes:
            includes = [f"<{inc}>" if not inc.startswith('"') else f'"{inc}"' for inc in includes[:5]]

        # Try to extract summary or any descriptive text
        summary_parts = []
        if target_file:
            summary_parts.append(f"Target file: {target_file}")
        if includes:
            summary_parts.append(f"Found {len(includes)} includes")

        # Look for keywords that indicate findings
        keywords = ["module", "dependency", "critical", "kernel", "framework"]
        for keyword in keywords:
            if keyword in submission.lower():
                summary_parts.append(f"mentions {keyword}")
                break

        if summary_parts:
            summary = "Topology analysis (text extraction): " + ", ".join(summary_parts)
        else:
            summary = "Topology analysis completed (minimal structured output available)"

        # Return best-effort insight
        return TopologyInsight(
            target_file=target_file or "unknown",
            affected_module=[],
            gn_dependency_files=[],
            direct_includes=includes if includes else [],
            summary=summary,
        )

    def _extract_history_insight(self, result: AgentRunResult) -> HistoryInsight:
        """Extract structured HistoryInsight from agent result.

        This method implements a four-tier extraction strategy:
        1. Try to extract from MAS result markers (preferred)
        2. Try to parse structured JSON from submission
        3. If submission empty, try to parse from trajectory
        4. If parsing fails, extract key information from text
        5. As last resort, return minimal default insight

        Args:
            result: Agent run result

        Returns:
            HistoryInsight
        """
        # TIER 1: Try to extract from MAS result markers (PREFERRED)
        mas_result = self._extract_mas_result(result)
        submission = mas_result if mas_result else result.info.get("submission") or ""

        # If submission is empty, try trajectory
        if not submission.strip():
            logger.warning("Temporal agent submission is empty, checking trajectory...")
            submission = self._extract_json_from_trajectory(result.trajectory)

        # Tier 1: Try to parse structured JSON
        json_match = re.search(r"\{[\s\S]*\}", submission)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return HistoryInsight.from_dict(data)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON from temporal agent: {e}")

        # Tier 2: Fallback - extract information from text
        logger.info("Attempting to extract history insights from unstructured text")

        # Try to extract commit hash
        blamed_commit = None
        commit_patterns = [
            r"commit[:\s]+([0-9a-f]{7,40})",
            r"blamed_commit[\"']?\s*:\s*[\"']([0-9a-f]{7,40})[\"']",
            r"\b([0-9a-f]{40})\b",  # Full SHA
            r"\b([0-9a-f]{7,12})\b",  # Short SHA (7-12 chars)
        ]
        for pattern in commit_patterns:
            match = re.search(pattern, submission, re.IGNORECASE)
            if match:
                blamed_commit = match.group(1)
                break

        # Try to extract author
        blamed_author = None
        author_patterns = [
            r"author[:\s]+([A-Za-z0-9_\-]+)",
            r"blamed_author[\"']?\s*:\s*[\"']([^\"']+)[\"']",
            r"by\s+([A-Za-z0-9_\-]+)",
        ]
        for pattern in author_patterns:
            match = re.search(pattern, submission, re.IGNORECASE)
            if match:
                blamed_author = match.group(1)
                break

        # Try to extract co-changing files
        co_changing = []
        file_pattern = r'([^\s]+\.[ch](?:pp)?)\b'
        files = re.findall(file_pattern, submission)
        if files:
            co_changing = list(set(files))[:5]  # Deduplicate and limit to 5

        # Build summary from extracted info
        summary_parts = []
        if blamed_commit:
            summary_parts.append(f"Commit: {blamed_commit[:8]}")
        if blamed_author:
            summary_parts.append(f"Author: {blamed_author}")
        if co_changing:
            summary_parts.append(f"{len(co_changing)} related files")

        # Look for temporal keywords
        temporal_keywords = ["month", "week", "version", "v3", "recent", "regression"]
        for keyword in temporal_keywords:
            if keyword in submission.lower():
                summary_parts.append(f"mentions {keyword}")
                break

        if summary_parts:
            change_pattern_summary = "History analysis (text extraction): " + ", ".join(summary_parts)
        else:
            change_pattern_summary = "History analysis completed (minimal structured output available)"

        # Return best-effort insight
        return HistoryInsight(
            blamed_commit=blamed_commit,
            blamed_author=blamed_author,
            co_changing_files=co_changing,
            change_pattern_summary=change_pattern_summary,
            potential_cause=None,
        )

    def _save_state(self) -> None:
        """Save current state to file."""
        state_path = self.output_dir / f"state_{self.state.task_id}.json"
        self.state.save(state_path)
        logger.debug(f"State saved to: {state_path}")
