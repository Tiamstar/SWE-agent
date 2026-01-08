#!/usr/bin/env python3
"""Test Harmony MAS on Defects4C dataset.

This script integrates the Harmony Multi-Agent System with Defects4C's online
evaluation platform. It fetches defects, uses harmony_mas to generate patches,
and submits them for verification.

Usage:
    # Test on a specific bug_id
    python tools/test_defects4c.py --bug_id <bug_id>

    # Test on a random defect (excluding llvm)
    python tools/test_defects4c.py --random

Example:
    python tools/test_defects4c.py --random --max_iterations 2
"""

import argparse
import hashlib
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import requests

# Apply swerex patch for devcontainer compatibility
from sweagent.deployment.docker_patched import patch_swerex_docker_deployment

patch_swerex_docker_deployment()

from sweagent.agent.mas.harmony_coordinator import HarmonyCoordinator
from sweagent.environment.repo import LocalRepoConfig
from sweagent.environment.swe_env import EnvironmentConfig, SWEEnv
from sweagent.utils.log import get_logger

logger = get_logger("defects4c-test", emoji="🧪")

# Defects4C API Configuration
DEFECTS4C_BASE_URL = "https://defects4c.wj2ai.com"


def get_defects_list(exclude_llvm: bool = True) -> list[str]:
    """Get list of available defects from Defects4C.

    Args:
        exclude_llvm: If True, filter out llvm defects (they are CPU intensive)

    Returns:
        List of bug IDs
    """
    logger.info("Fetching defects list from Defects4C...")
    response = requests.get(f"{DEFECTS4C_BASE_URL}/list_defects_bugid")
    data = response.json()

    if data.get("status") != "success":
        raise RuntimeError(f"Failed to get defects list: {data}")

    defects = data["defects"]

    if exclude_llvm:
        defects = [d for d in defects if "llvm___llvm" not in d]
        logger.info(f"Found {len(defects)} defects (excluding llvm)")
    else:
        logger.info(f"Found {len(defects)} defects")

    return defects


def get_defect_info(bug_id: str) -> dict[str, Any]:
    """Get detailed information for a specific defect.

    Args:
        bug_id: Bug identifier

    Returns:
        Defect data dictionary
    """
    logger.info(f"Fetching defect info for: {bug_id}")
    response = requests.get(f"{DEFECTS4C_BASE_URL}/get_defect/{bug_id}")
    data = response.json()

    if data.get("status") != "success":
        raise RuntimeError(f"Failed to get defect info: {data}")

    return data


def extract_issue_description(defect_data: dict[str, Any]) -> str:
    """Extract issue description from defect data.

    The Defects4C API provides prompts in a messages format.
    We need to convert this to a single issue description string
    that harmony_mas can understand.

    Args:
        defect_data: Defect data from API

    Returns:
        Issue description string
    """
    prompts = defect_data["prompt_data"]["prompt"]

    # Extract user messages (skip system messages)
    user_messages = [
        msg["content"]
        for msg in prompts
        if msg["role"] == "user"
    ]

    # Combine all user messages into a single description
    issue_description = "\n\n".join(user_messages)

    logger.info(f"Extracted issue description ({len(issue_description)} chars)")
    logger.debug(f"Preview: {issue_description[:200]}...")

    return issue_description


def download_defect_repo(bug_id: str, work_dir: Path) -> Path:
    """Download the defect repository to local workspace.

    Note: Defects4C may provide repository information in the defect data.
    For now, we'll create a minimal local repo structure.

    Args:
        bug_id: Bug identifier
        work_dir: Working directory for downloads

    Returns:
        Path to local repository
    """
    # Create a work directory for this bug
    repo_dir = work_dir / bug_id.replace("___", "_").replace("/", "_")
    repo_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Repository workspace: {repo_dir}")

    # TODO: In a real implementation, you would:
    # 1. Extract repository URL from defect_data
    # 2. Clone the repository at the buggy commit
    # 3. Apply any necessary setup steps

    # For now, we return the directory and assume Defects4C handles the repo
    return repo_dir


def build_patch_from_harmony_mas(
    bug_id: str,
    issue_description: str,
    repo_path: Path,
    max_iterations: int = 3,
    num_candidate_patches: int = 3,
) -> str:
    """Use Harmony MAS to generate a patch for the defect.

    Args:
        bug_id: Bug identifier
        issue_description: Issue description text
        repo_path: Path to local repository
        max_iterations: Max refinement iterations
        num_candidate_patches: Number of candidate patches

    Returns:
        Generated patch as string
    """
    logger.info("=" * 80)
    logger.info("RUNNING HARMONY MAS")
    logger.info("=" * 80)

    # Generate project_id from bug_id
    project_id = hashlib.sha256(bug_id.encode()).hexdigest()[:16]

    try:
        # Step 1: Create repository instance
        repo = LocalRepoConfig(path=repo_path)

        # Step 2: Create environment configuration
        env_config = EnvironmentConfig(
            repo=repo,
            deployment={
                "type": "docker",
                "image": "python:3.11",
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
        config_dir = Path("config/agents")
        coordinator = HarmonyCoordinator.from_config_files(
            env=env,
            topology_config_path=config_dir / "topology_agent.yaml",
            temporal_config_path=config_dir / "temporal_agent.yaml",
            patch_generator_config_path=config_dir / "patch_generator_agent.yaml",
            review_config_path=config_dir / "review_agent.yaml",
            contract_config_path=config_dir / "contract_agent.yaml",
            coordinator_config_path=config_dir / "coordinator_agent.yaml",
            output_dir=Path("trajectories") / "defects4c" / bug_id,
            max_iterations=max_iterations,
            num_candidate_patches=num_candidate_patches,
        )

        # Step 5: Run the workflow
        task_id = f"DEFECTS4C-{bug_id}"
        patch = coordinator.run(
            issue_description=issue_description,
            task_id=task_id,
        )

        logger.info("=" * 80)
        logger.info("HARMONY MAS COMPLETED")
        logger.info("=" * 80)

        return patch

    except Exception as e:
        logger.exception(f"Harmony MAS failed: {e}")
        raise


def submit_patch_to_defects4c(
    bug_id: str,
    patch_content: str,
    method: str = "direct",
) -> dict[str, Any]:
    """Submit generated patch to Defects4C for building.

    Args:
        bug_id: Bug identifier
        patch_content: Patch diff content
        method: Build method ("direct" or other)

    Returns:
        Build response data
    """
    logger.info("Submitting patch to Defects4C...")

    payload = {
        "bug_id": bug_id,
        "llm_response": patch_content,
        "method": method,
        "generate_diff": True,
        "persist_flag": True,
    }

    response = requests.post(
        f"{DEFECTS4C_BASE_URL}/build_patch",
        headers={'Content-Type': 'application/json'},
        json=payload,
    )

    data = response.json()

    if not data.get("success"):
        logger.error(f"Patch build failed: {data}")
        return data

    logger.info(f"Patch built successfully: {data.get('fix_p')}")

    if "patch_content" in data:
        logger.debug("Patch content preview:")
        logger.debug(data["patch_content"][:500])

    return data


def verify_patch(bug_id: str, patch_path: str) -> str:
    """Submit patch for verification and return handle.

    Args:
        bug_id: Bug identifier
        patch_path: Path to built patch (returned by build_patch)

    Returns:
        Verification handle for polling status
    """
    logger.info("Submitting patch for verification...")

    payload = {
        "bug_id": bug_id,
        "patch_path": patch_path,
    }

    response = requests.post(
        f"{DEFECTS4C_BASE_URL}/fix2",
        headers={'Content-Type': 'application/json'},
        json=payload,
    )

    data = response.json()
    handle = data["handle"]

    logger.info(f"Verification submitted, handle: {handle}")

    return handle


def poll_verification_status(
    handle: str,
    max_wait: int = 300,
    poll_interval: int = 10,
) -> dict[str, Any]:
    """Poll verification status until completion.

    Args:
        handle: Verification handle
        max_wait: Maximum wait time in seconds
        poll_interval: Polling interval in seconds

    Returns:
        Final status data
    """
    logger.info("Polling verification status...")

    start_time = time.time()

    while time.time() - start_time < max_wait:
        response = requests.get(f"{DEFECTS4C_BASE_URL}/status/{handle}")
        status_data = response.json()

        status_completed = status_data.get("status", "unknown")
        is_completed = status_completed == "completed"

        logger.info(f"Status: {status_completed} (completed: {is_completed})")

        if is_completed:
            fix_status = status_data.get("fix_status")
            if fix_status == "success":
                logger.info("✅ Fix successful!")
            else:
                logger.error(f"❌ Fix failed: {status_data.get('error', 'Unknown error')}")

            return status_data

        logger.info(f"Waiting {poll_interval} seconds...")
        time.sleep(poll_interval)

    logger.error("Timeout waiting for verification")
    return {"status": "timeout", "error": "Exceeded maximum wait time"}


def save_results(bug_id: str, results: dict[str, Any], output_dir: Path):
    """Save test results to JSON file.

    Args:
        bug_id: Bug identifier
        results: Results dictionary
        output_dir: Output directory
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    result_file = output_dir / f"{bug_id.replace('/', '_')}.json"

    with open(result_file, 'w') as f:
        json.dump(results, f, indent=2)

    logger.info(f"Results saved to: {result_file}")


def main():
    """Main entry point for Defects4C testing."""
    parser = argparse.ArgumentParser(
        description="Test Harmony MAS on Defects4C dataset",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--bug_id",
        type=str,
        help="Specific bug ID to test (e.g., 'curl___curl-for-win___e5f0d')",
    )

    parser.add_argument(
        "--random",
        action="store_true",
        help="Select a random defect to test",
    )

    parser.add_argument(
        "--exclude_llvm",
        action="store_true",
        default=True,
        help="Exclude llvm defects (default: True)",
    )

    parser.add_argument(
        "--repo_path",
        type=str,
        help="Path to local repository (optional, will be downloaded if not provided)",
    )

    parser.add_argument(
        "--max_iterations",
        type=int,
        default=3,
        help="Max iterations for patch refinement (default: 3)",
    )

    parser.add_argument(
        "--num_candidate_patches",
        type=int,
        default=3,
        help="Number of candidate patches (default: 3)",
    )

    parser.add_argument(
        "--work_dir",
        type=str,
        default="work/defects4c",
        help="Working directory for downloads (default: work/defects4c)",
    )

    parser.add_argument(
        "--output_dir",
        type=str,
        default="results/defects4c",
        help="Output directory for results (default: results/defects4c)",
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.bug_id and not args.random:
        logger.error("Must specify either --bug_id or --random")
        sys.exit(1)

    # Create directories
    work_dir = Path(args.work_dir)
    output_dir = Path(args.output_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Print banner
    logger.info("=" * 80)
    logger.info("DEFECTS4C + HARMONY MAS TEST")
    logger.info("=" * 80)

    results = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "max_iterations": args.max_iterations,
            "num_candidate_patches": args.num_candidate_patches,
        },
    }

    try:
        # Step 1: Get bug_id
        if args.random:
            defects = get_defects_list(exclude_llvm=args.exclude_llvm)
            bug_id = random.choice(defects)
            logger.info(f"Randomly selected: {bug_id}")
        else:
            bug_id = args.bug_id
            logger.info(f"Testing bug: {bug_id}")

        results["bug_id"] = bug_id

        # Step 2: Get defect information
        defect_data = get_defect_info(bug_id)
        issue_description = extract_issue_description(defect_data)

        results["issue_description"] = issue_description[:500] + "..." if len(issue_description) > 500 else issue_description

        # Step 3: Prepare repository
        if args.repo_path:
            repo_path = Path(args.repo_path)
        else:
            repo_path = download_defect_repo(bug_id, work_dir)

        results["repo_path"] = str(repo_path)

        # Step 4: Run Harmony MAS to generate patch
        logger.info("\n" + "=" * 80)
        logger.info("STEP 1: GENERATE PATCH WITH HARMONY MAS")
        logger.info("=" * 80)

        patch_content = build_patch_from_harmony_mas(
            bug_id=bug_id,
            issue_description=issue_description,
            repo_path=repo_path,
            max_iterations=args.max_iterations,
            num_candidate_patches=args.num_candidate_patches,
        )

        results["generated_patch"] = patch_content
        logger.info(f"\nGenerated patch ({len(patch_content)} chars):")
        logger.info("-" * 80)
        logger.info(patch_content[:1000])
        logger.info("-" * 80)

        # Step 5: Submit patch to Defects4C
        logger.info("\n" + "=" * 80)
        logger.info("STEP 2: SUBMIT PATCH TO DEFECTS4C")
        logger.info("=" * 80)

        build_response = submit_patch_to_defects4c(bug_id, patch_content)

        if not build_response.get("success"):
            results["build_status"] = "failed"
            results["build_error"] = build_response.get("message", "Unknown error")
            logger.error(f"Build failed: {results['build_error']}")
            save_results(bug_id, results, output_dir)
            sys.exit(1)

        results["build_status"] = "success"
        results["patch_path"] = build_response["fix_p"]

        # Step 6: Verify patch
        logger.info("\n" + "=" * 80)
        logger.info("STEP 3: VERIFY PATCH")
        logger.info("=" * 80)

        handle = verify_patch(bug_id, build_response["fix_p"])
        results["verification_handle"] = handle

        # Step 7: Poll for results
        logger.info("\n" + "=" * 80)
        logger.info("STEP 4: WAIT FOR VERIFICATION")
        logger.info("=" * 80)

        verification_status = poll_verification_status(handle)
        results["verification_status"] = verification_status

        # Step 8: Save results
        save_results(bug_id, results, output_dir)

        # Print summary
        logger.info("\n" + "=" * 80)
        logger.info("TEST SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Bug ID: {bug_id}")
        logger.info(f"Build: {results['build_status']}")
        logger.info(f"Verification: {verification_status.get('fix_status', 'unknown')}")

        if verification_status.get("fix_status") == "success":
            logger.info("✅ TEST PASSED")
            sys.exit(0)
        else:
            logger.info("❌ TEST FAILED")
            sys.exit(1)

    except Exception as e:
        logger.exception(f"Test failed with error: {e}")
        results["error"] = str(e)
        save_results(bug_id if 'bug_id' in locals() else "unknown", results, output_dir)
        sys.exit(1)


if __name__ == "__main__":
    main()
