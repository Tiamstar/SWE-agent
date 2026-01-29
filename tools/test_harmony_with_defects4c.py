#!/usr/bin/env python3
"""Test Harmony MAS with Defects4C benchmark.

This script integrates the Harmony Multi-Agent System with Defects4C
to test bug fixing capabilities on C/C++ projects.

Usage:
    python tools/test_harmony_with_defects4c.py --bug_id "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082"
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

# Apply swerex patch for devcontainer compatibility
from sweagent.deployment.docker_patched import patch_swerex_docker_deployment

patch_swerex_docker_deployment()

from sweagent.agent.mas.harmony_coordinator import HarmonyCoordinator
from sweagent.environment.repo import LocalRepoConfig
from sweagent.environment.swe_env import EnvironmentConfig, SWEEnv
from sweagent.utils.log import get_logger

logger = get_logger("harmony-defects4c", emoji="🧪")

# Defects4C API configuration
DEFECTS4C_BASE_URL = "https://defects4c.wj2ai.com"


def get_defect_info(bug_id: str) -> dict:
    """Get defect information from Defects4C API.

    Args:
        bug_id: Bug identifier in format "project@commit_sha"

    Returns:
        Dictionary containing defect information
    """
    logger.info(f"Fetching defect info for {bug_id}")
    response = requests.get(f"{DEFECTS4C_BASE_URL}/get_defect/{bug_id}")
    data = response.json()

    if data.get("status") != "success":
        raise ValueError(f"Failed to get defect info: {data}")

    return data


def extract_file_and_function_from_prompt(prompt_data: dict) -> tuple[str, str]:
    """Extract file path and function name from Defects4C prompt.

    Args:
        prompt_data: Prompt data from Defects4C API

    Returns:
        Tuple of (file_path, function_name)
    """
    # The prompt typically contains the buggy function and file information
    prompts = prompt_data.get("prompt", [])

    # Look for user message containing the buggy code
    for msg in prompts:
        if msg.get("role") == "user":
            content = msg.get("content", "")

            # Try to extract file path from content
            # Pattern: "file: path/to/file.cpp"
            file_match = re.search(r"file:\s*([^\n]+)", content, re.IGNORECASE)
            if file_match:
                file_path = file_match.group(1).strip()
            else:
                file_path = "unknown"

            # Try to extract function name from code block
            # Pattern: function definition like "void functionName(...)"
            func_match = re.search(r"(?:void|int|bool|char|static|const)\s+(\w+)\s*\(", content)
            if func_match:
                function_name = func_match.group(1)
            else:
                function_name = "unknown"

            return file_path, function_name

    return "unknown", "unknown"


def create_issue_description(defect_data: dict) -> str:
    """Create issue description for Harmony MAS from Defects4C data.

    Args:
        defect_data: Defect data from Defects4C API

    Returns:
        Issue description string
    """
    prompt_data = defect_data.get("prompt_data", {})
    prompts = prompt_data.get("prompt", [])

    # Extract the problem description from prompts
    problem_desc = ""
    for msg in prompts:
        if msg.get("role") == "user":
            problem_desc = msg.get("content", "")
            break

    # Extract file and function info
    file_path, function_name = extract_file_and_function_from_prompt(prompt_data)

    # Create a structured issue description
    issue = f"""Bug Fix Request from Defects4C Benchmark

File: {file_path}
Function: {function_name}

Problem Description:
{problem_desc}

Task: Fix the bug in the specified function to pass all unit tests.
"""

    return issue


def extract_code_from_response(response: str) -> str:
    """Extract code from Harmony MAS response.

    Args:
        response: Response from Harmony MAS

    Returns:
        Extracted code
    """
    # Look for code blocks in markdown format
    code_blocks = re.findall(r"```(?:cpp|c|c\+\+)?\n(.*?)```", response, re.DOTALL)

    if code_blocks:
        # Return the last code block (usually the final fix)
        return code_blocks[-1].strip()

    # If no code blocks found, return the whole response
    return response


def submit_patch_to_defects4c(bug_id: str, llm_response: str) -> dict:
    """Submit patch to Defects4C for verification.

    Args:
        bug_id: Bug identifier
        llm_response: LLM response containing the fix

    Returns:
        Patch submission result
    """
    logger.info("Building patch with Defects4C API")

    patch_payload = {
        "bug_id": bug_id,
        "llm_response": llm_response,
        "method": "direct",
        "generate_diff": True,
        "persist_flag": True,
    }

    response = requests.post(
        f"{DEFECTS4C_BASE_URL}/build_patch",
        headers={"Content-Type": "application/json"},
        json=patch_payload,
    )

    patch_data = response.json()

    if not patch_data.get("success"):
        logger.error(f"Failed to build patch: {patch_data}")
        return patch_data

    logger.info(f"Patch created: {patch_data.get('fix_p')}")

    # Submit for verification
    logger.info("Submitting patch for verification")
    fix_payload = {
        "bug_id": bug_id,
        "patch_path": patch_data["fix_p"],
    }

    fix_response = requests.post(
        f"{DEFECTS4C_BASE_URL}/fix2",
        headers={"Content-Type": "application/json"},
        json=fix_payload,
    )

    fix_data = fix_response.json()
    handle = fix_data["handle"]
    logger.info(f"Fix submitted, handle: {handle}")

    # Poll for results
    return wait_for_verification(handle)


def wait_for_verification(handle: str, max_wait: int = 300, poll_interval: int = 10) -> dict:
    """Wait for patch verification to complete.

    Args:
        handle: Task handle from fix submission
        max_wait: Maximum wait time in seconds
        poll_interval: Polling interval in seconds

    Returns:
        Verification result
    """
    logger.info("Waiting for verification results...")
    start_time = time.time()

    while time.time() - start_time < max_wait:
        response = requests.get(f"{DEFECTS4C_BASE_URL}/status/{handle}")
        status_data = response.json()

        status_completed = status_data.get("status", "unknown")

        if status_completed == "completed":
            fix_status = status_data.get("fix_status")
            if fix_status == "success":
                logger.info("✅ Fix successful!")
            else:
                logger.warning(f"❌ Fix failed: {status_data.get('error', 'Unknown error')}")
            return status_data

        logger.info(f"Status: {status_completed}, waiting {poll_interval} seconds...")
        time.sleep(poll_interval)

    logger.error("Verification timeout")
    return {"status": "timeout", "error": "Verification timed out"}


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test Harmony MAS with Defects4C benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--bug_id",
        type=str,
        required=True,
        help='Bug ID in format "project@commit_sha" (e.g., "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082")',
    )

    parser.add_argument(
        "--repo_path",
        type=str,
        default=None,
        help="Local repository path (if not provided, will use a temporary clone)",
    )

    parser.add_argument(
        "--coordinator_config",
        type=str,
        default="config/agents/coordinator_agent.yaml",
        help="Path to coordinator configuration file",
    )

    parser.add_argument(
        "--max_iterations",
        type=int,
        default=3,
        help="Max iterations for patch refinement",
    )

    parser.add_argument(
        "--output_dir",
        type=str,
        default="trajectories/defects4c_tests",
        help="Output directory for results",
    )

    parser.add_argument(
        "--api_only",
        action="store_true",
        help="Use only Defects4C API without running Harmony MAS (for testing API integration)",
    )

    args = parser.parse_args()

    # Step 1: Get defect information
    try:
        defect_data = get_defect_info(args.bug_id)
    except Exception as e:
        logger.error(f"Failed to get defect info: {e}")
        return 1

    logger.info(f"Defect type: {defect_data.get('type', {}).get('name', 'Unknown')}")

    # Step 2: Create issue description
    issue_description = create_issue_description(defect_data)
    logger.info(f"Issue description:\n{issue_description}")

    if args.api_only:
        logger.info("API-only mode: skipping Harmony MAS execution")
        return 0

    # Step 3: Run Harmony MAS to generate fix
    logger.info("Running Harmony MAS to generate fix...")

    # For now, we'll use a mock response since we need to integrate with your actual system
    # You would replace this with actual Harmony MAS execution
    logger.warning("⚠️  Mock mode: Please integrate with your actual Harmony MAS system")
    logger.info("To integrate:")
    logger.info("1. Clone the repository specified in bug_id")
    logger.info("2. Run your Harmony MAS with the issue description")
    logger.info("3. Extract the generated fix")
    logger.info("4. Submit to Defects4C API for verification")

    # Mock response for demonstration
    mock_response = """Here's the fixed function:

```cpp
// Fixed version of the function
void fixedFunction() {
    // Implementation
}
```
"""

    # Step 4: Submit to Defects4C for verification
    logger.info("Submitting fix to Defects4C for verification...")
    verification_result = submit_patch_to_defects4c(args.bug_id, mock_response)

    # Step 5: Report results
    logger.info("=" * 60)
    logger.info("VERIFICATION RESULTS")
    logger.info("=" * 60)
    logger.info(json.dumps(verification_result, indent=2))

    # Save results
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result_file = output_dir / f"{args.bug_id.replace('/', '_').replace('@', '_')}_result.json"
    with open(result_file, "w") as f:
        json.dump(
            {
                "bug_id": args.bug_id,
                "defect_data": defect_data,
                "issue_description": issue_description,
                "verification_result": verification_result,
            },
            f,
            indent=2,
        )

    logger.info(f"Results saved to {result_file}")

    return 0 if verification_result.get("fix_status") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
