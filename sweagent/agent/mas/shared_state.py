"""Shared State Object for Harmony Multi-Agent System.

This module implements the centralized state management for the HarmonyOS
warning repair multi-agent system. The SharedState class acts as the
"Single Source of Truth" for the entire workflow.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from sweagent.utils.log import get_logger

logger = get_logger("harmony-shared-state", emoji="📊")


class WorkflowStage(str, Enum):
    """Workflow stages for the Harmony MAS state machine."""

    INITIALIZED = "INITIALIZED"
    WARNING_DISCOVERY = "WARNING_DISCOVERY"  # cppcheck scan for all warnings
    WARNING_TRIAGE = "WARNING_TRIAGE"  # LLM selects most important warning
    ANALYSIS_TOPOLOGY = "ANALYSIS_TOPOLOGY"
    ANALYSIS_HISTORY = "ANALYSIS_HISTORY"
    PATCH_GENERATION = "PATCH_GENERATION"  # Unified state (handles both initial and retry)
    VERIFICATION = "VERIFICATION"  # Renamed from VERIFICATION_REVIEW for clarity
    FINALIZING = "FINALIZING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"


@dataclass
class WarningItem:
    """Single cppcheck warning record."""

    id: str  # warning_001, warning_002, ...
    file_path: str  # src/foo.c
    line_number: int  # 142
    severity: str  # warning, error, performance, style
    message: str  # "Potential null pointer dereference"
    raw_output: str  # Original cppcheck output line
    priority_score: float = 0.0  # LLM-assigned priority (0.0-1.0)
    selection_reason: str = ""  # Why LLM selected this warning

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WarningItem:
        """Create from dictionary."""
        return cls(**data)


@dataclass
class TopologyInsight:
    """Structured output from Topology Analysis Agent."""

    insight_type: str = "topology"
    target_file: str = ""
    affected_module: list[str] = field(default_factory=list)
    gn_dependency_files: list[str] = field(default_factory=list)
    direct_includes: list[str] = field(default_factory=list)
    criticality_score: float = 0.0  # 0.0 - 1.0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TopologyInsight:
        """Create from dictionary."""
        return cls(**data)


@dataclass
class HistoryInsight:
    """Structured output from Temporal Awareness Agent."""

    insight_type: str = "history"
    blamed_commit: str = ""
    blamed_author: str = ""
    co_changing_files: list[str] = field(default_factory=list)
    change_pattern_summary: str = ""
    potential_cause: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryInsight:
        """Create from dictionary."""
        return cls(**data)


@dataclass
class ReviewInsight:
    """Structured output from Review Agent (DEPRECATED - use VerificationInsight)."""

    insight_type: str = "verification_review"
    patch_id: str = ""
    status: str = ""  # "COMPILE_SUCCESS", "COMPILE_FAILED", etc.
    execution_time_ms: int = 0
    error_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewInsight:
        """Create from dictionary."""
        return cls(**data)


@dataclass
class ContractInsight:
    """Structured output from Contract & Impact Agent (DEPRECATED - use VerificationInsight)."""

    insight_type: str = "verification_review"
    patch_id: str = ""
    is_safe: bool = False
    risk_score: float = 0.0  # 0.0 - 1.0
    violation_list: list[dict[str, str]] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContractInsight:
        """Create from dictionary."""
        # Handle nested violation_list
        return cls(**data)


@dataclass
class VerificationInsight:
    """Unified structured output from Verification Agent (combines Review + Contract)."""

    insight_type: str = "verification"
    patch_id: str = ""
    is_safe: bool = False
    quality_score: float = 0.0  # 0.0-1.0, from static analysis
    risk_score: float = 0.0  # 0.0-1.0, from contract check
    overall_score: float = 0.0  # Combined score
    static_analysis: dict[str, Any] = field(default_factory=dict)
    contract_check: dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerificationInsight:
        """Create from dictionary."""
        return cls(**data)


@dataclass
class CandidatePatch:
    """A candidate patch with its verification status."""

    id: str
    diff_content: str
    verification_status: str = "PENDING"  # PENDING, SAFE, UNSAFE
    verification_errors: str = ""
    quality_score: float | None = None  # From static analysis
    risk_score: float | None = None  # From contract check
    overall_score: float | None = None  # Combined score
    last_updated_by: str = "Coordinator"
    verification_insight: VerificationInsight | None = None

    # Legacy fields (deprecated but kept for backward compatibility with old code)
    review_status: str = "PENDING"
    review_risk_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        if self.verification_insight:
            data["verification_insight"] = self.verification_insight.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CandidatePatch:
        """Create from dictionary."""
        verification_data = data.pop("verification_insight", None)
        # Remove obsolete fields if present
        data.pop("contract_insight", None)
        data.pop("build_status", None)
        data.pop("build_errors", None)
        patch = cls(**data)
        if verification_data:
            patch.verification_insight = VerificationInsight.from_dict(verification_data)
        return patch


@dataclass
class FinalPatch:
    """The final approved patch."""

    id: str = "patch_final"
    diff_content: str = ""
    description: str = ""
    verification_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FinalPatch:
        """Create from dictionary."""
        return cls(**data)


@dataclass
class SharedState:
    """Centralized state object for Harmony MAS workflow.

    This class represents the "Single Source of Truth" for the entire
    multi-agent workflow. All agents read from and write to this state
    through the coordinator.

    Attributes:
        task_id: Unique identifier for this repair task
        current_stage: Current workflow stage (state machine position)
        initial_requirement: Original warning/issue description
        discovered_warnings: All warnings found by cppcheck scan
        selected_warning: The single warning chosen for repair (by LLM)
        context_insights: Structured insights from analysis agents
        candidate_patches: List of generated patch candidates
        final_patch: The approved final patch
        retry_history: History of failed patch generation attempts
        metadata: Additional metadata (timestamps, etc.)
    """

    task_id: str
    current_stage: WorkflowStage = WorkflowStage.INITIALIZED
    initial_requirement: str = ""
    discovered_warnings: list[WarningItem] = field(default_factory=list)
    selected_warning: WarningItem | None = None
    context_insights: dict[str, Any] = field(default_factory=dict)
    candidate_patches: list[CandidatePatch] = field(default_factory=list)
    final_patch: FinalPatch | None = None
    retry_history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Initialize metadata with creation timestamp."""
        if "created_at" not in self.metadata:
            self.metadata["created_at"] = datetime.now().isoformat()
        self.metadata["last_updated"] = datetime.now().isoformat()

    def update_stage(self, new_stage: WorkflowStage) -> None:
        """Update the workflow stage.

        Args:
            new_stage: New workflow stage
        """
        self.current_stage = new_stage
        self.metadata["last_updated"] = datetime.now().isoformat()
        self.metadata[f"entered_{new_stage.value}_at"] = datetime.now().isoformat()

    def add_topology_insight(self, insight: TopologyInsight) -> None:
        """Add topology analysis results.

        Args:
            insight: TopologyInsight object
        """
        self.context_insights["topology"] = insight.to_dict()
        self.metadata["last_updated"] = datetime.now().isoformat()

    def add_history_insight(self, insight: HistoryInsight) -> None:
        """Add temporal analysis results.

        Args:
            insight: HistoryInsight object
        """
        self.context_insights["history"] = insight.to_dict()
        self.metadata["last_updated"] = datetime.now().isoformat()

    def add_candidate_patch(self, patch: CandidatePatch) -> None:
        """Add a candidate patch.

        Args:
            patch: CandidatePatch object
        """
        self.candidate_patches.append(patch)
        self.metadata["last_updated"] = datetime.now().isoformat()

    def update_patch_build_status(self, patch_id: str, status: str, errors: str = "") -> None:
        """Update build status for a candidate patch (DEPRECATED - use update_patch_verification).

        This method is deprecated and kept only for backward compatibility.

        Args:
            patch_id: Patch identifier
            status: Build status (COMPILE_SUCCESS, COMPILE_FAILED, etc.)
            errors: Error messages if failed
        """
        logger.warning("update_patch_build_status is deprecated, use update_patch_verification instead")
        # This method is deprecated but we keep it for backward compatibility
        # It now does nothing since build_status field was removed
        self.metadata["last_updated"] = datetime.now().isoformat()

    def update_patch_review_status(
        self,
        patch_id: str,
        contract_insight: ContractInsight,
    ) -> None:
        """Update review status for a candidate patch (DEPRECATED - use update_patch_verification).

        This method is deprecated and kept only for backward compatibility.

        Args:
            patch_id: Patch identifier
            contract_insight: ContractInsight from Contract Agent
        """
        logger.warning("update_patch_review_status is deprecated, use update_patch_verification instead")
        # This method is deprecated but we keep it for backward compatibility
        # Map old contract_insight to new verification_insight
        for patch in self.candidate_patches:
            if patch.id == patch_id:
                patch.review_status = "SAFE" if contract_insight.is_safe else "UNSAFE"
                patch.review_risk_score = contract_insight.risk_score
                patch.last_updated_by = "Contract Agent"
                self.metadata["last_updated"] = datetime.now().isoformat()
                break

    def update_patch_verification(
        self,
        patch_id: str,
        verification_insight: VerificationInsight,
    ) -> None:
        """Update verification status for a candidate patch.

        Args:
            patch_id: Patch identifier
            verification_insight: VerificationInsight from Verification Agent
        """
        for patch in self.candidate_patches:
            if patch.id == patch_id:
                patch.verification_status = "SAFE" if verification_insight.is_safe else "UNSAFE"
                patch.quality_score = verification_insight.quality_score
                patch.risk_score = verification_insight.risk_score
                patch.overall_score = verification_insight.overall_score
                patch.verification_insight = verification_insight
                patch.last_updated_by = "Verification Agent"

                # Update legacy fields for backward compatibility
                patch.review_status = "SAFE" if verification_insight.is_safe else "UNSAFE"
                patch.review_risk_score = verification_insight.risk_score

                self.metadata["last_updated"] = datetime.now().isoformat()
                break

    def set_final_patch(self, patch: FinalPatch) -> None:
        """Set the final approved patch.

        Args:
            patch: FinalPatch object
        """
        self.final_patch = patch
        self.metadata["last_updated"] = datetime.now().isoformat()

    def get_best_candidate(self) -> CandidatePatch | None:
        """Get the best candidate patch based on verification status.

        Returns:
            Best candidate patch or None if no suitable candidate
        """
        # Prefer new verification_status field, fallback to legacy fields
        safe_patches = []
        for p in self.candidate_patches:
            # Check new field first
            if p.verification_status == "SAFE":
                safe_patches.append(p)
            # Fallback to legacy review_status field
            elif p.review_status == "SAFE":
                safe_patches.append(p)

        if safe_patches:
            # Return the safest one based on overall_score or risk_score
            def get_score(p: CandidatePatch) -> float:
                if p.overall_score is not None:
                    return p.overall_score  # Higher is better
                elif p.risk_score is not None:
                    return 1.0 - p.risk_score  # Lower risk is better
                elif p.review_risk_score is not None:
                    return 1.0 - p.review_risk_score  # Legacy fallback
                return 0.5  # Neutral default

            return max(safe_patches, key=get_score)

        # If no safe patches, return None (don't compromise on safety)
        return None

    def prepare_for_retry(self) -> None:
        """Prepare state for patch generation retry.

        This method:
        1. Saves current failed patches to retry history
        2. Extracts violations from failed patches
        3. Clears candidate patches for next iteration
        """
        # Save current attempt to history
        retry_record = {
            "iteration": len(self.retry_history) + 1,
            "timestamp": datetime.now().isoformat(),
            "failed_patches": [p.to_dict() for p in self.candidate_patches],
            "violations": [],
        }

        # Collect violations from all failed patches using verification_insight
        for patch in self.candidate_patches:
            if patch.verification_insight and patch.verification_insight.contract_check:
                violation_list = patch.verification_insight.contract_check.get("violation_list", [])
                if violation_list:
                    retry_record["violations"].extend(violation_list)

        self.retry_history.append(retry_record)

        # Clear candidate patches for next iteration
        self.candidate_patches = []
        self.metadata["last_updated"] = datetime.now().isoformat()

    def get_retry_count(self) -> int:
        """Get the number of patch generation retries.

        Returns:
            Number of retry attempts made so far
        """
        return len(self.retry_history)

    def get_accumulated_violations(self) -> list[dict[str, str]]:
        """Get all violations from previous retry attempts.

        This provides context for the next patch generation attempt
        to avoid repeating the same mistakes.

        Returns:
            List of violation dictionaries from all previous attempts
        """
        violations = []
        for retry in self.retry_history:
            violations.extend(retry.get("violations", []))
        return violations

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation
        """
        return {
            "task_id": self.task_id,
            "current_stage": self.current_stage.value,
            "initial_requirement": self.initial_requirement,
            "discovered_warnings": [w.to_dict() for w in self.discovered_warnings],
            "selected_warning": self.selected_warning.to_dict() if self.selected_warning else None,
            "context_insights": self.context_insights,
            "candidate_patches": [p.to_dict() for p in self.candidate_patches],
            "final_patch": self.final_patch.to_dict() if self.final_patch else None,
            "retry_history": self.retry_history,
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string.

        Args:
            indent: JSON indentation level

        Returns:
            JSON string
        """
        return json.dumps(self.to_dict(), indent=indent)

    def save(self, file_path: Path) -> None:
        """Save state to JSON file.

        Args:
            file_path: Path to save the state
        """
        with open(file_path, "w") as f:
            f.write(self.to_json())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SharedState:
        """Create SharedState from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            SharedState instance
        """
        # Convert stage string to enum
        stage = WorkflowStage(data.get("current_stage", "INITIALIZED"))

        # Convert warnings
        warnings = [WarningItem.from_dict(w) for w in data.get("discovered_warnings", [])]

        # Convert selected warning
        selected_warning_data = data.get("selected_warning")
        selected_warning = WarningItem.from_dict(selected_warning_data) if selected_warning_data else None

        # Convert patches
        patches = [CandidatePatch.from_dict(p) for p in data.get("candidate_patches", [])]

        # Convert final patch
        final_patch_data = data.get("final_patch")
        final_patch = FinalPatch.from_dict(final_patch_data) if final_patch_data else None

        return cls(
            task_id=data["task_id"],
            current_stage=stage,
            initial_requirement=data.get("initial_requirement", ""),
            discovered_warnings=warnings,
            selected_warning=selected_warning,
            context_insights=data.get("context_insights", {}),
            candidate_patches=patches,
            final_patch=final_patch,
            retry_history=data.get("retry_history", []),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def load(cls, file_path: Path) -> SharedState:
        """Load state from JSON file.

        Args:
            file_path: Path to the state file

        Returns:
            SharedState instance
        """
        with open(file_path) as f:
            data = json.load(f)
        return cls.from_dict(data)
