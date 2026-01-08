"""Simplified Multi-Agent System with Smart Repository Caching.

This script provides a cleaner interface with intelligent repository management:
- First run: clones repo to local cache
- Subsequent runs: reuses cached repo (no re-cloning)
- Containers are ephemeral but repos are persistent

Usage:
    # First run - clones repo to cache
    python tools/run_mas_simple.py \
        --repo https://github.com/owner/repo \
        --issue "Bug description"

    # Subsequent runs - reuses cached repo (much faster!)
    python tools/run_mas_simple.py \
        --repo https://github.com/owner/repo \
        --issue "Another bug"

    # Or use local repo directly
    python tools/run_mas_simple.py \
        --repo /path/to/local/repo \
        --issue "Bug description"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from sweagent.agent.mas.coordinator import RepairCoordinator, load_agent_config_from_yaml
from sweagent.environment.repo import GithubRepoConfig, LocalRepoConfig
from sweagent.environment.swe_env import EnvironmentConfig, SWEEnv
from sweagent.utils.log import get_logger
from swerex.deployment.config import DockerDeploymentConfig

logger = get_logger("run-mas-simple", emoji="🚀")

# Cache directory for cloned repositories
CACHE_DIR = Path.home() / ".swe-agent" / "repo-cache"
STATE_FILE = CACHE_DIR / "cache_state.json"


def load_cache_state() -> dict[str, Any]:
    """Load cache state."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_cache_state(state: dict[str, Any]) -> None:
    """Save cache state."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_repo_cache_path(repo_url: str) -> Path:
    """Get cache path for a repository."""
    # Create a safe directory name from repo URL
    if repo_url.startswith("http"):
        # Extract owner/repo from GitHub URL
        parts = repo_url.rstrip("/").split("/")
        repo_name = f"{parts[-2]}_{parts[-1]}"
    else:
        # For local repos, use the directory name
        repo_name = Path(repo_url).name

    return CACHE_DIR / repo_name


def clone_or_update_repo(repo_url: str, cache_path: Path) -> None:
    """Clone repo to cache or update if already exists."""
    if not repo_url.startswith("http"):
        # Local repo, no caching needed
        return

    if cache_path.exists():
        logger.info(f"Updating cached repository: {cache_path}")
        try:
            subprocess.run(
                ["git", "-C", str(cache_path), "fetch", "--all"],
                check=True,
                capture_output=True,
                timeout=60,
            )
            subprocess.run(
                ["git", "-C", str(cache_path), "reset", "--hard", "HEAD"],
                check=True,
                capture_output=True,
                timeout=30,
            )
            logger.info("Cache updated successfully")
        except Exception as e:
            logger.warning(f"Failed to update cache: {e}")
            logger.info("Will use existing cache as-is")
    else:
        logger.info(f"Cloning repository to cache: {cache_path}")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            github_token = os.getenv("GITHUB_TOKEN", "")
            clone_url = repo_url
            if github_token and "@" not in repo_url:
                # Add token to URL
                _, _, url_no_protocol = repo_url.partition("://")
                clone_url = f"https://{github_token}@{url_no_protocol}"

            subprocess.run(
                ["git", "clone", clone_url, str(cache_path)],
                check=True,
                capture_output=True,
                timeout=300,
            )
            logger.info("Repository cloned successfully")

            # Update cache state
            state = load_cache_state()
            state[repo_url] = {
                "cache_path": str(cache_path),
                "last_used": str(Path.cwd()),
            }
            save_cache_state(state)

        except Exception as e:
            logger.error(f"Failed to clone repository: {e}")
            if cache_path.exists():
                import shutil
                shutil.rmtree(cache_path)
            raise


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Simplified Multi-Agent System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Core required options
    parser.add_argument(
        "--repo",
        required=True,
        help="Repository (local path or GitHub URL)",
    )
    parser.add_argument(
        "--issue",
        required=True,
        help="Issue description (text, file path, or GitHub issue URL)",
    )

    # Optional configuration
    parser.add_argument(
        "--rca-config",
        type=Path,
        default=Path("config/agents/rca_agent.yaml"),
        help="RCA agent config",
    )
    parser.add_argument(
        "--patch-config",
        type=Path,
        default=Path("config/agents/patch_agent.yaml"),
        help="Patch agent config",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory",
    )
    parser.add_argument(
        "--docker-image",
        default="python:3.11",
        help="Docker image",
    )

    # Cache control
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Don't use repository cache (always clone fresh)",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear repository cache and exit",
    )

    # Patch application options
    parser.add_argument(
        "--apply-patch",
        action="store_true",
        help="Automatically apply the generated patch to the local repository",
    )
    parser.add_argument(
        "--save-patch",
        type=Path,
        help="Save the generated patch to a file (e.g., --save-patch fix.patch)",
    )

    # Neo4j (optional)
    parser.add_argument("--neo4j-uri", help="Neo4j URI")
    parser.add_argument("--neo4j-user", help="Neo4j user")
    parser.add_argument("--neo4j-password", help="Neo4j password")

    parser.add_argument("--request-id", default="default", help="Request ID")

    return parser.parse_args()


def main():
    """Main entry point."""
    # Fix Docker permissions if needed
    docker_socket = "/var/run/docker.sock"
    if os.path.exists(docker_socket):
        try:
            subprocess.run(
                ["sudo", "chmod", "666", docker_socket],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass

    args = parse_args()

    # Handle cache clearing
    if args.clear_cache:
        if CACHE_DIR.exists():
            import shutil
            shutil.rmtree(CACHE_DIR)
            logger.info("Repository cache cleared")
        else:
            logger.info("No cache to clear")
        return 0

    logger.info("=" * 70)
    logger.info("Multi-Agent System - Simplified Mode")
    logger.info("=" * 70)

    # Setup repository
    logger.info("\nSetting up repository...")

    if args.repo.startswith("http"):
        # GitHub repo - use cache
        cache_path = get_repo_cache_path(args.repo)

        if args.no_cache:
            logger.info("Cache disabled, will clone fresh")
            if cache_path.exists():
                import shutil
                shutil.rmtree(cache_path)

        clone_or_update_repo(args.repo, cache_path)
        repo_config = LocalRepoConfig(path=cache_path)
        logger.info(f"Using cached repository: {cache_path}")
    else:
        # Local repo
        repo_config = LocalRepoConfig(path=Path(args.repo))
        logger.info(f"Using local repository: {args.repo}")

    # Setup environment
    deployment_config = DockerDeploymentConfig(
        image=args.docker_image,
        python_standalone_dir="/root",
    )

    env_config = EnvironmentConfig(
        repo=repo_config,
        deployment=deployment_config,
    )

    # Neo4j setup
    post_startup_commands = []
    neo4j_uri = args.neo4j_uri or os.getenv("NEO4J_URI")
    neo4j_user = args.neo4j_user or os.getenv("NEO4J_USER")
    neo4j_password = args.neo4j_password or os.getenv("NEO4J_PASSWORD")

    if neo4j_uri:
        post_startup_commands.append(f"export NEO4J_URI='{neo4j_uri}'")
    if neo4j_user:
        post_startup_commands.append(f"export NEO4J_USER='{neo4j_user}'")
    if neo4j_password:
        post_startup_commands.append(f"export NEO4J_PASSWORD='{neo4j_password}'")

    if post_startup_commands:
        env_config.post_startup_commands.extend(post_startup_commands)

    # Create environment
    env = SWEEnv.from_config(env_config)

    # Load issue
    logger.info("\nLoading issue...")
    if args.issue.startswith("http") and "github.com" in args.issue and "/issues/" in args.issue:
        from sweagent.utils.github import _get_problem_statement_from_github_issue, _parse_gh_issue_url
        owner, repo, issue_number = _parse_gh_issue_url(args.issue)
        issue_description = _get_problem_statement_from_github_issue(owner, repo, issue_number)
    elif Path(args.issue).exists():
        issue_description = Path(args.issue).read_text()
    else:
        issue_description = args.issue

    # Load configs
    logger.info("\nLoading agent configurations...")
    rca_config = load_agent_config_from_yaml(args.rca_config)
    patch_config = load_agent_config_from_yaml(args.patch_config)

    # Create coordinator
    coordinator = RepairCoordinator(
        env=env,
        rca_config=rca_config,
        patch_config=patch_config,
        output_dir=args.output_dir,
        keep_env_alive=False,  # Containers are ephemeral
    )

    # Run workflow
    logger.info("\n" + "=" * 70)
    logger.info("Starting repair workflow...")
    logger.info("=" * 70)

    try:
        final_patch = coordinator.run(
            issue_description=issue_description,
            request_id=args.request_id,
        )

        logger.info("\n" + "=" * 70)
        logger.info("REPAIR COMPLETED")
        logger.info("=" * 70)
        print("\nFINAL PATCH:")
        print(final_patch)

        # Handle patch saving and application
        if args.save_patch:
            from sweagent.utils.patch import save_patch_to_file
            save_patch_to_file(final_patch, args.save_patch)
            logger.info(f"\n✓ Patch saved to: {args.save_patch}")

        if args.apply_patch:
            from sweagent.utils.patch import apply_patch_to_directory

            logger.info("\n" + "=" * 70)
            logger.info("APPLYING PATCH TO LOCAL REPOSITORY")
            logger.info("=" * 70)

            # Determine the target directory and whether to use git
            if args.repo.startswith("http"):
                # For GitHub repos, use the cache path (always Git)
                cache_path = get_repo_cache_path(args.repo)
                target_dir = cache_path
                use_git_apply = True  # GitHub repos are always Git
                logger.info(f"Target: {target_dir} (cached Git repository)")
            else:
                # For local repos, use the original path
                target_dir = Path(args.repo)
                # Use git apply if original was a Git repo, patch command otherwise
                use_git_apply = repo_config.is_original_git_repo
                repo_type = "Git repository" if use_git_apply else "non-Git directory"
                logger.info(f"Target: {target_dir} ({repo_type})")

            # First, do a dry run to check if patch can be applied
            logger.info("\nChecking if patch can be applied...")
            success, message = apply_patch_to_directory(
                final_patch,
                target_dir,
                dry_run=True,
                use_git=use_git_apply,
            )

            if success:
                logger.info(f"✓ {message}")
                logger.info("\nApplying patch...")
                success, message = apply_patch_to_directory(
                    final_patch,
                    target_dir,
                    dry_run=False,
                    use_git=use_git_apply,
                )

                if success:
                    logger.info(f"✓ {message}")
                    logger.info("\n" + "=" * 70)
                    logger.info("PATCH APPLIED SUCCESSFULLY!")
                    logger.info("=" * 70)
                else:
                    logger.error(f"✗ Failed to apply patch: {message}")
                    return 1
            else:
                logger.error(f"✗ Patch cannot be applied: {message}")
                logger.info("\nSaving patch to file for manual application...")
                patch_file = Path("failed_patch.patch")
                from sweagent.utils.patch import save_patch_to_file
                save_patch_to_file(final_patch, patch_file)
                logger.info(f"Patch saved to: {patch_file}")
                logger.info("You can try to apply it manually with:")
                logger.info(f"  patch -p1 < {patch_file}")
                return 1

        return 0

    except Exception as e:
        logger.exception(f"Workflow failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
