#!/usr/bin/env python3
"""Harmony MAS Demo Script.

This script demonstrates the Harmony Multi-Agent System for fixing
HarmonyOS repository-level warnings in C/C++ code.

Usage:
    python tools/run_harmony_mas.py --repo_path /path/to/repo --issue "warning description"

Example:
    python tools/run_harmony_mas.py \\
        --repo_path /path/to/harmonyos/repo \\
        --issue "src/foundation/ace/adapter.cpp:142: warning: Potential null pointer dereference"
"""

import argparse
import sys
import hashlib
from pathlib import Path

# Apply swerex patch for devcontainer compatibility
from sweagent.deployment.docker_patched import patch_swerex_docker_deployment

patch_swerex_docker_deployment()

from sweagent.agent.mas.harmony_coordinator import HarmonyCoordinator
from sweagent.environment.repo import LocalRepoConfig
from sweagent.environment.swe_env import EnvironmentConfig, SWEEnv
from sweagent.utils.log import get_logger

logger = get_logger("harmony-mas-demo", emoji="🚀")


def main():
    """Main entry point for Harmony MAS demo."""
    parser = argparse.ArgumentParser(
        description="Harmony Multi-Agent System for HarmonyOS Warning Repair",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--repo_path",
        type=str,
        required=True,
        help="Path to local repository (HarmonyOS/C++ project)",
    )

    parser.add_argument(
        "--issue",
        type=str,
        required=True,
        help="Warning/issue description to fix",
    )

    parser.add_argument(
        "--task_id",
        type=str,
        default=None,
        help="Optional task ID (default: auto-generated)",
    )

    parser.add_argument(
        "--output_dir",
        type=str,
        default=None,
        help="Output directory for trajectories (default: trajectories/harmony_mas_<timestamp>)",
    )

    parser.add_argument(
        "--max_iterations",
        type=int,
        default=3,
        help="Max iterations for patch refinement loop (default: 3)",
    )

    parser.add_argument(
        "--num_candidate_patches",
        type=int,
        default=3,
        help="Number of candidate patches to generate per iteration (default: 3, range: 1-5)",
    )

    parser.add_argument(
        "--coordinator_config",
        type=str,
        default="config/agents/coordinator_agent.yaml",
        help="Path to coordinator configuration file (default: config/agents/coordinator_agent.yaml)",
    )

    parser.add_argument(
        "--image",
        type=str,
        default="python:3.11",
        help="Docker image to use (default: python:3.11)",
    )

    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Clean up project data from Neo4j after completion (default: False)",
    )

    args = parser.parse_args()

    # Validate repo path
    repo_path = Path(args.repo_path).resolve()
    if not repo_path.exists():
        logger.error(f"Repository path does not exist: {repo_path}")
        sys.exit(1)

    # Generate project_id from repo path
    project_id = hashlib.sha256(str(repo_path).encode()).hexdigest()[:16]

    # Print banner
    logger.info("=" * 80)
    logger.info("HARMONY MULTI-AGENT SYSTEM (MAS)")
    logger.info("HarmonyOS Repository-Level Warning Repair")
    logger.info("=" * 80)
    logger.info(f"Repository: {repo_path}")
    logger.info(f"Project ID: {project_id}")
    logger.info(f"Issue: {args.issue[:100]}...")
    logger.info(f"Max iterations: {args.max_iterations}")
    logger.info(f"Candidate patches: {args.num_candidate_patches}")
    logger.info(f"Coordinator config: {args.coordinator_config}")
    logger.info(f"Cleanup after completion: {args.cleanup}")
    logger.info("=" * 80)

    try:
        # Step 1: Create repository instance
        logger.info("\n[1/4] Initializing repository...")
        repo = LocalRepoConfig(
            path=repo_path,
        )

        # Step 2: Create environment configuration
        logger.info("\n[2/4] Setting up environment...")
        env_config = EnvironmentConfig(
            repo=repo,
            deployment={
                "type": "docker",
                "image": args.image,
                "startup_timeout": 600.0,
                "docker_args": [
                    "--network", "swe-agent_devcontainer_default",
                    "-e", "NEO4J_URI=bolt://swe-agent_devcontainer-neo4j-1:7687",
                    "-e", "NEO4J_USER=neo4j",
                    "-e", "NEO4J_PASSWORD=swe-agent-local",
                    "-e", f"HARMONY_PROJECT_ID={project_id}",
                ],
            },
        )

        # Step 3: Create shared SWEEnv
        env = SWEEnv.from_config(env_config)

        # Step 4: Create Harmony Coordinator
        logger.info("\n[3/4] Initializing Harmony Coordinator...")

        # Agent config paths
        config_dir = Path("config/agents")
        topology_config = config_dir / "topology_agent.yaml"
        temporal_config = config_dir / "temporal_agent.yaml"
        patch_generator_config = config_dir / "patch_generator_agent.yaml"
        verification_config = config_dir / "verification_agent.yaml"  # Unified verification
        coordinator_config = Path(args.coordinator_config) if args.coordinator_config else None

        # Verify config files exist
        for config_path in [topology_config, temporal_config, patch_generator_config, verification_config]:
            if not config_path.exists():
                logger.error(f"Agent config not found: {config_path}")
                sys.exit(1)

        # Verify coordinator config if provided
        if coordinator_config and not coordinator_config.exists():
            logger.warning(f"Coordinator config not found: {coordinator_config}")
            logger.warning("Using default coordinator prompts")
            coordinator_config = None

        # Create coordinator
        coordinator = HarmonyCoordinator.from_config_files(
            env=env,
            topology_config_path=topology_config,
            temporal_config_path=temporal_config,
            patch_generator_config_path=patch_generator_config,
            verification_config_path=verification_config,  # Unified verification
            coordinator_config_path=coordinator_config,
            output_dir=Path(args.output_dir) if args.output_dir else None,
            max_iterations=args.max_iterations,
            num_candidate_patches=args.num_candidate_patches,
        )

        # Step 5: Run the workflow
        logger.info("\n[4/4] Executing Harmony MAS workflow...")
        logger.info("=" * 80)

        final_patch = coordinator.run(
            issue_description=args.issue,
            task_id=args.task_id,
        )

        # Step 6: Display results
        logger.info("\n" + "=" * 80)
        logger.info("WORKFLOW COMPLETED")
        logger.info("=" * 80)
        logger.info("\nFinal Patch:")
        logger.info("-" * 80)
        print(final_patch)
        logger.info("-" * 80)

        # Display output locations
        if coordinator.output_dir:
            logger.info(f"\nOutput directory: {coordinator.output_dir}")
            logger.info("Files generated:")
            logger.info(f"  - state_*.json: Shared state object snapshots")
            logger.info(f"  - topology/: Topology agent trajectories")
            logger.info(f"  - temporal/: Temporal agent trajectories")
            logger.info(f"  - patch_generator/: Patch generator agent trajectories")
            logger.info(f"  - verification/: Verification agent trajectories")

        logger.info("\n✓ Harmony MAS completed successfully!")

        # Step 7: Cleanup if requested
        if args.cleanup:
            logger.info("\n[Cleanup] Removing project data from Neo4j...")
            try:
                from tools.harmony_graph.lib.core import CodeGraphAgent

                agent = CodeGraphAgent()
                agent.delete_project(project_id)
                agent.close()
                logger.info(f"✓ Project {project_id} data removed from database")
            except Exception as e:
                logger.warning(f"Cleanup failed (non-fatal): {e}")

    except Exception as e:
        logger.exception(f"Harmony MAS failed: {e}")

        # Cleanup on failure if requested
        if args.cleanup:
            logger.info("\n[Cleanup] Task failed, removing project data...")
            try:
                from tools.harmony_graph.lib.core import CodeGraphAgent

                agent = CodeGraphAgent()
                agent.delete_project(project_id)
                agent.close()
            except:
                pass  # Ignore cleanup errors on failure

        sys.exit(1)


if __name__ == "__main__":
    main()
