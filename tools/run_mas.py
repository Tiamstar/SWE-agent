"""Entry point for MARRS (Multi-Agent Repository Repair System) with Star Topology.

This script demonstrates the Hub-and-Spoke architecture where:
- The Coordinator (Hub) manages the workflow and shared environment
- Specialized agents (Spokes) only communicate with the Coordinator
- Context flows through the Coordinator (no peer-to-peer communication)

Usage:
    # Create new container
    python tools/run_mas.py --repo <github_url> --issue <issue_url>
    python tools/run_mas.py --repo /path/to/local/repo --issue_text "Bug description"
    
    # Use existing container
    python tools/run_mas.py --use_existing_container <container_name> \\
        --container_repo_path /workspace --issue_text "Bug description" \\
        --neo4j_uri neo4j+s://your.database.io --neo4j_user neo4j --neo4j_password <password>
    
    # With Neo4j configuration
    python tools/run_mas.py --repo <repo> --issue <issue> \\
        --neo4j_uri neo4j+s://your.database.io \\
        --neo4j_user neo4j \\
        --neo4j_password <password>
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sweagent.agent.mas.coordinator import RepairCoordinator, load_agent_config_from_yaml
from sweagent.environment.repo import GithubRepoConfig, LocalRepoConfig, PreExistingRepoConfig
from sweagent.environment.swe_env import EnvironmentConfig, SWEEnv
from sweagent.utils.log import get_logger
from swerex.deployment.config import DockerDeploymentConfig

logger = get_logger("run-mas", emoji="🚀")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run MARRS (Multi-Agent Repository Repair System) with Star Topology",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Repository options
    parser.add_argument(
        "--repo",
        required=True,
        help="Repository to analyze (GitHub URL or local path)",
    )

    # Issue options (one required)
    issue_group = parser.add_mutually_exclusive_group(required=True)
    issue_group.add_argument(
        "--issue",
        help="GitHub issue URL (e.g., https://github.com/owner/repo/issues/123)",
    )
    issue_group.add_argument(
        "--issue_text",
        help="Issue description as text",
    )
    issue_group.add_argument(
        "--issue_file",
        type=Path,
        help="Path to file containing issue description",
    )

    # Configuration options
    parser.add_argument(
        "--rca_config",
        type=Path,
        default=Path("config/agents/rca_agent.yaml"),
        help="Path to RCA agent config (default: config/agents/rca_agent.yaml)",
    )
    parser.add_argument(
        "--patch_config",
        type=Path,
        default=Path("config/agents/patch_agent.yaml"),
        help="Path to Patch agent config (default: config/agents/patch_agent.yaml)",
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=None,
        help="Output directory (default: auto-generated timestamped dir in trajectories/)",
    )

    # Environment options
    parser.add_argument(
        "--docker_image",
        default="python:3.11",
        help="Docker image to use (default: python:3.11)",
    )

    # Existing container options
    parser.add_argument(
        "--use_existing_container",
        default=None,
        help="Use an existing Docker container instead of creating a new one (container name or ID)",
    )
    parser.add_argument(
        "--container_repo_path",
        default="workspace",
        help="Path to repository in the existing container (default: workspace)",
    )
    parser.add_argument(
        "--container_python_dir",
        default="/root",
        help="Python standalone directory in container (default: /root)",
    )

    # Neo4j configuration options
    parser.add_argument(
        "--neo4j_uri",
        default=None,
        help="Neo4j database URI (default: from environment or all_local.py config)",
    )
    parser.add_argument(
        "--neo4j_user",
        default=None,
        help="Neo4j username (default: from environment or all_local.py config)",
    )
    parser.add_argument(
        "--neo4j_password",
        default=None,
        help="Neo4j password (default: from environment or all_local.py config)",
    )

    parser.add_argument(
        "--request_id",
        default="default",
        help="Request identifier for this run (default: 'default')",
    )

    return parser.parse_args()


def get_issue_description(args) -> str:
    """Get issue description from command line arguments."""
    if args.issue:
        # Fetch from GitHub issue URL
        from sweagent.utils.github import _get_problem_statement_from_github_issue, _parse_gh_issue_url

        owner, repo, issue_number = _parse_gh_issue_url(args.issue)
        # This function returns a string directly, not a dict
        issue_description = _get_problem_statement_from_github_issue(owner, repo, issue_number)
        return issue_description

    elif args.issue_text:
        return args.issue_text

    elif args.issue_file:
        return args.issue_file.read_text()

    else:
        raise ValueError("No issue description provided")


def main():
    """Main entry point for MARRS."""
    # Fix Docker permissions if needed (in dev container, permissions can be reset)
    import subprocess

    docker_socket = "/var/run/docker.sock"
    if os.path.exists(docker_socket):
        try:
            subprocess.run(
                ["sudo", "chmod", "666", docker_socket],
                capture_output=True,
                timeout=5,
            )
        except Exception as e:
            logger.warning(f"Failed to fix Docker permissions: {e}")

    args = parse_args()

    logger.info("=" * 70)
    logger.info("MARRS - Multi-Agent Repository Repair System (Star Topology)")
    logger.info("=" * 70)

    # Get issue description
    logger.info("Loading issue description...")
    issue_description = get_issue_description(args)
    logger.info(f"  Issue preview: {issue_description[:200]}...")

    # Setup environment configuration
    logger.info("\nSetting up environment configuration...")

    # Determine repo config based on input
    if args.use_existing_container:
        # Using existing container - repo should already exist there
        logger.info(f"Using existing container: {args.use_existing_container}")
        repo_config = PreExistingRepoConfig(
            repo_name=args.container_repo_path,
            base_commit="HEAD",
            reset=True,
        )
        # For existing containers, we use PreExistingRepoConfig without creating a new deployment
        env_config = EnvironmentConfig(repo=repo_config)
    else:
        # Create new container from image
        if args.repo.startswith("http"):
            repo_config = GithubRepoConfig(github_url=args.repo)
        else:
            repo_config = LocalRepoConfig(path=Path(args.repo))

        deployment_config = DockerDeploymentConfig(
            image=args.docker_image,
            python_standalone_dir="/root",
        )
        env_config = EnvironmentConfig(
            repo=repo_config,
            deployment=deployment_config,
        )

    # Prepare post-startup commands to set Neo4j environment variables
    post_startup_commands = []
    
    # Collect Neo4j configuration from args or environment
    neo4j_uri = args.neo4j_uri or os.getenv("NEO4J_URI")
    neo4j_user = args.neo4j_user or os.getenv("NEO4J_USER")
    neo4j_password = args.neo4j_password or os.getenv("NEO4J_PASSWORD")
    
    if neo4j_uri:
        post_startup_commands.append(f"export NEO4J_URI='{neo4j_uri}'")
        logger.info(f"  Neo4j URI configured: {neo4j_uri}")
    if neo4j_user:
        post_startup_commands.append(f"export NEO4J_USER='{neo4j_user}'")
    if neo4j_password:
        post_startup_commands.append(f"export NEO4J_PASSWORD='{neo4j_password}'")
    
    # Apply post-startup commands to environment config
    if post_startup_commands:
        env_config.post_startup_commands.extend(post_startup_commands)

    # Create shared environment (will be started by first agent)
    logger.info("Creating shared environment...")
    env = SWEEnv.from_config(env_config)
    logger.info(f"  Environment instance: {id(env)}")

    # Load agent configurations
    logger.info("\nLoading agent configurations...")
    rca_config = load_agent_config_from_yaml(args.rca_config)
    logger.info(f"  RCA config loaded: {rca_config.name}")
    patch_config = load_agent_config_from_yaml(args.patch_config)
    logger.info(f"  Patch config loaded: {patch_config.name}")

    # Create coordinator (The Hub)
    logger.info("\nInitializing Star Topology Coordinator...")
    coordinator = RepairCoordinator(
        env=env,
        rca_config=rca_config,
        patch_config=patch_config,
        output_dir=args.output_dir,
    )

    # Run the repair workflow
    logger.info("\n" + "=" * 70)
    logger.info("Starting repair workflow...")
    logger.info("=" * 70 + "\n")

    try:
        final_patch = coordinator.run(
            issue_description=issue_description,
            request_id=args.request_id,
        )

        # Display results
        logger.info("REPAIR WORKFLOW COMPLETED")
        print("FINAL PATCH:")
        print(final_patch)

        return 0

    except Exception as e:
        logger.exception(f"Repair workflow failed: {e}")
        print(f"\nERROR: Repair workflow failed - {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
