#!/usr/bin/env python3
"""Complete integration of Harmony MAS with Defects4C benchmark.

This script provides end-to-end testing of Harmony MAS on Defects4C bugs:
1. Fetches bug information from Defects4C API
2. Clones the repository and checks out the buggy commit
3. Constructs issue description from bug data
4. Runs Harmony MAS to generate fix
5. Extracts the generated patch
6. Submits to Defects4C for verification
7. Reports results

Usage:
    python tools/run_defects4c_test.py --bug_id "danmar___cppcheck@099b4435c38dd52ddb38e6b1706d9c988699c082"
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

# Apply swerex patch for devcontainer compatibility
from sweagent.deployment.docker_patched import patch_swerex_docker_deployment

patch_swerex_docker_deployment()

from sweagent.agent.mas.harmony_coordinator import HarmonyCoordinator
from sweagent.environment.repo import LocalRepoConfig
from sweagent.environment.swe_env import EnvironmentConfig, SWEEnv
from sweagent.utils.log import get_logger

logger = get_logger("defects4c-test", emoji="🧪")

# Defects4C API configuration
DEFECTS4C_BASE_URL = "https://defects4c.wj2ai.com"


class Defects4CIntegration:
    """Integration handler for Defects4C benchmark testing."""

    def __init__(
        self,
        bug_id: str,
        work_dir: Path,
        coordinator_config: Path,
        max_iterations: int = 3,
        num_candidate_patches: int = 3,
        docker_image: str = "python:3.11",
    ):
        """Initialize Defects4C integration.

        Args:
            bug_id: Bug identifier in format "project@commit_sha"
            work_dir: Working directory for cloning repos and storing results
            coordinator_config: Path to coordinator configuration file
            max_iterations: Max iterations for patch refinement
            num_candidate_patches: Number of candidate patches to generate
            docker_image: Docker image to use for environment
        """
        self.bug_id = bug_id
        self.work_dir = Path(work_dir)
        self.coordinator_config = Path(coordinator_config)
        self.max_iterations = max_iterations
        self.num_candidate_patches = num_candidate_patches
        self.docker_image = docker_image

        # Parse bug_id
        self.project_name, self.commit_sha = self._parse_bug_id(bug_id)
        self.repo_owner, self.repo_name = self._parse_project_name(self.project_name)

        # Paths
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.repo_dir = self.work_dir / "repos" / self.project_name
        self.results_dir = self.work_dir / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Initialized Defects4C integration for {bug_id}")
        logger.info(f"  Project: {self.project_name}")
        logger.info(f"  Commit: {self.commit_sha}")
        logger.info(f"  Work dir: {self.work_dir}")

    def _parse_bug_id(self, bug_id: str) -> Tuple[str, str]:
        """Parse bug_id into project name and commit SHA."""
        parts = bug_id.split("@")
        if len(parts) != 2:
            raise ValueError(f"Invalid bug_id format: {bug_id}. Expected 'project@commit_sha'")
        return parts[0], parts[1]

    def _parse_project_name(self, project_name: str) -> Tuple[str, str]:
        """Parse project name into owner and repo."""
        parts = project_name.split("___")
        if len(parts) != 2:
            raise ValueError(f"Invalid project name: {project_name}. Expected 'owner___repo'")
        return parts[0], parts[1]

    def fetch_bug_info(self) -> Dict:
        """Fetch bug information from Defects4C API.

        Returns:
            Dictionary containing bug information
        """
        logger.info(f"Fetching bug info from Defects4C API...")
        response = requests.get(f"{DEFECTS4C_BASE_URL}/get_defect/{self.bug_id}", timeout=30)

        if response.status_code != 200:
            raise RuntimeError(f"Failed to fetch bug info: HTTP {response.status_code}")

        data = response.json()
        if data.get("status") != "success":
            raise RuntimeError(f"API returned error: {data}")

        logger.info(f"✅ Successfully fetched bug info")
        return data

    def clone_repository(self) -> Path:
        """Clone the repository and checkout the buggy commit.

        Returns:
            Path to the cloned repository
        """
        github_url = f"https://github.com/{self.repo_owner}/{self.repo_name}.git"

        logger.info(f"Cloning repository: {github_url}")

        # Remove existing repo if it exists
        if self.repo_dir.exists():
            logger.info(f"Removing existing repo at {self.repo_dir}")
            shutil.rmtree(self.repo_dir)

        # Clone the repository
        self.repo_dir.parent.mkdir(parents=True, exist_ok=True)

        # Strategy: Start with shallow clone, then fetch specific commit
        try:
            # Step 1: Shallow clone to get repository structure
            logger.info("Step 1: Performing shallow clone...")
            subprocess.run(
                ["git", "clone", "--depth", "1", github_url, str(self.repo_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("✅ Shallow clone completed")

            # Step 2: Fetch the specific commit
            logger.info(f"Step 2: Fetching specific commit {self.commit_sha[:8]}...")
            try:
                subprocess.run(
                    ["git", "fetch", "--depth", "1", "origin", self.commit_sha],
                    cwd=self.repo_dir,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                logger.info("✅ Specific commit fetched")
            except subprocess.CalledProcessError:
                # If fetching specific commit fails, unshallow the repository
                logger.info("Fetching specific commit failed, unshallowing repository...")
                subprocess.run(
                    ["git", "fetch", "--unshallow"],
                    cwd=self.repo_dir,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                logger.info("✅ Repository unshallowed")

        except subprocess.CalledProcessError:
            # If shallow clone strategy fails completely, do full clone
            logger.warning("Shallow clone strategy failed, performing full clone...")
            if self.repo_dir.exists():
                shutil.rmtree(self.repo_dir)
            subprocess.run(
                ["git", "clone", github_url, str(self.repo_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("✅ Full clone completed")

        logger.info(f"✅ Repository cloned to {self.repo_dir}")

        # Checkout the buggy commit
        logger.info(f"Step 3: Checking out buggy commit {self.commit_sha[:8]}...")
        try:
            subprocess.run(
                ["git", "checkout", self.commit_sha],
                cwd=self.repo_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info(f"✅ Checked out commit {self.commit_sha}")
        except subprocess.CalledProcessError as e:
            # Print more detailed error information
            logger.error(f"Failed to checkout commit {self.commit_sha}")
            logger.error(f"Git error: {e.stderr if hasattr(e, 'stderr') else 'No error message'}")

            # Try to verify if commit exists
            result = subprocess.run(
                ["git", "cat-file", "-t", self.commit_sha],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.error(f"Commit {self.commit_sha} does not exist in repository")
                logger.info("Attempting to fetch all history...")
                subprocess.run(
                    ["git", "fetch", "--unshallow"],
                    cwd=self.repo_dir,
                    capture_output=True,
                    text=True,
                )
                # Retry checkout
                subprocess.run(
                    ["git", "checkout", self.commit_sha],
                    cwd=self.repo_dir,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                logger.info(f"✅ Checked out commit {self.commit_sha} after unshallow")
            else:
                raise

        return self.repo_dir

    def construct_issue_description(self, bug_data: Dict) -> str:
        """Construct issue description from Defects4C bug data.

        Args:
            bug_data: Bug data from Defects4C API

        Returns:
            Issue description string suitable for Harmony MAS
        """
        # Get file path from local metadata
        file_path = self._get_file_path_from_metadata(bug_data)

        # Get bug type
        bug_type = bug_data.get("type", {}).get("name", "Unknown bug type")
        bug_category = bug_data.get("type", {}).get("id", "Unknown")

        # Extract the buggy code from API
        prompt_data = bug_data.get("prompt_data", {})
        prompts = prompt_data.get("prompt", [])

        buggy_code_full = ""
        for msg in prompts:
            if msg.get("role") == "user":
                buggy_code_full = msg.get("content", "")
                break

        # Extract the buggy hunk (the code that was removed)
        buggy_hunk_match = re.search(
            r"This was the original buggy hunk.*?```cpp\n// buggy hunk\n(.*?)\n```",
            buggy_code_full,
            re.DOTALL
        )
        buggy_hunk = buggy_hunk_match.group(1).strip() if buggy_hunk_match else "See full context below"

        # Extract function name from the code
        func_match = re.search(
            r"(?:static\s+)?(?:void|int|bool|char|const|unsigned|signed|long|short|float|double|size_t|std::string)\s+(\w+)\s*\(",
            buggy_code_full,
        )
        function_name = func_match.group(1) if func_match else "unknown"

        # Construct a concise issue description
        issue = f"""Fix bug in {file_path} function {function_name}()

Bug type: {bug_type}

The buggy code that was removed:
```cpp
{buggy_hunk}
```

Task: Fix the bug to pass all tests.
"""

        logger.info(f"Constructed issue description for {file_path} ({len(issue)} chars)")
        return issue

    def _get_file_path_from_metadata(self, bug_data: Dict) -> str:
        """Extract file path from bug metadata.

        Args:
            bug_data: Bug data from Defects4C API

        Returns:
            File path relative to repository root
        """
        # Try to get from prompt_data idx field
        prompt_data = bug_data.get("prompt_data", {})
        idx = prompt_data.get("idx", "")

        if "___" in idx:
            # Format: "commit_sha___filename.cpp"
            parts = idx.split("___")
            if len(parts) >= 2:
                filename = parts[1]
                # Try to find the file in the repository
                # Common locations for C++ projects
                possible_paths = [
                    f"lib/{filename}",
                    f"src/{filename}",
                    f"source/{filename}",
                    filename,
                ]

                # Check which path exists
                for path in possible_paths:
                    full_path = self.repo_dir / path
                    if full_path.exists():
                        logger.info(f"Found file at: {path}")
                        return path

                # If not found, try the first common location
                logger.warning(f"File {filename} not found, using lib/{filename}")
                return f"lib/{filename}"

        # Fallback: try to extract from local bugs_list_new.json
        try:
            bugs_list_path = Path("/workspaces/SWE-agent/defects4c-master/defectsc_tpl/projects_v1") / self.project_name / "bugs_list_new.json"
            if bugs_list_path.exists():
                with open(bugs_list_path) as f:
                    bugs_list = json.load(f)
                    for bug in bugs_list:
                        if self.commit_sha in str(bug.get("commit_after", "")):
                            files = bug.get("files", {})
                            src_files = files.get("src", [])
                            if src_files:
                                logger.info(f"Found file from metadata: {src_files[0]}")
                                return src_files[0]
        except Exception as e:
            logger.warning(f"Could not read local metadata: {e}")

        # Final fallback
        logger.warning("Could not determine file path, using 'unknown'")
        return "unknown"

    def run_harmony_mas(self, repo_path: Path, issue: str) -> Dict:
        """Run Harmony MAS to generate fix.

        Args:
            repo_path: Path to the repository
            issue: Issue description

        Returns:
            Dictionary containing Harmony MAS results
        """
        logger.info("=" * 80)
        logger.info("RUNNING HARMONY MULTI-AGENT SYSTEM")
        logger.info("=" * 80)

        # Generate project_id
        project_id = hashlib.sha256(str(repo_path).encode()).hexdigest()[:16]

        try:
            # Step 1: Create repository instance
            logger.info("[1/5] Initializing repository...")
            repo = LocalRepoConfig(path=repo_path)

            # Step 2: Create environment configuration
            logger.info("[2/5] Setting up environment...")
            env_config = EnvironmentConfig(
                repo=repo,
                deployment={
                    "type": "docker",
                    "image": self.docker_image,
                    "startup_timeout": 600.0,
                    "docker_args": [
                        "--network",
                        "swe-agent_devcontainer_default",
                        "-e",
                        "NEO4J_URI=bolt://swe-agent_devcontainer-neo4j-1:7687",
                        "-e",
                        "NEO4J_USER=neo4j",
                        "-e",
                        "NEO4J_PASSWORD=swe-agent-local",
                        "-e",
                        f"HARMONY_PROJECT_ID={project_id}",
                    ],
                },
            )

            # Step 3: Create environment
            logger.info("[3/5] Creating SWE environment...")
            env = SWEEnv.from_config(env_config)

            # Step 4: Load agent configurations
            logger.info("[4/5] Loading agent configurations...")
            config_base = self.coordinator_config.parent

            topology_config_path = config_base / "topology_agent.yaml"
            temporal_config_path = config_base / "temporal_agent.yaml"
            patch_generator_config_path = config_base / "patch_generator_agent.yaml"
            verification_config_path = config_base / "verification_agent.yaml"

            # Verify config files exist
            for config_path in [
                topology_config_path,
                temporal_config_path,
                patch_generator_config_path,
                verification_config_path,
            ]:
                if not config_path.exists():
                    raise FileNotFoundError(f"Agent config not found: {config_path}")

            # Step 5: Create and run coordinator
            logger.info("[5/5] Running Harmony Coordinator...")
            coordinator = HarmonyCoordinator.from_config_files(
                env=env,
                topology_config_path=topology_config_path,
                temporal_config_path=temporal_config_path,
                patch_generator_config_path=patch_generator_config_path,
                verification_config_path=verification_config_path,
                coordinator_config_path=self.coordinator_config if self.coordinator_config.exists() else None,
                output_dir=self.results_dir / "harmony_output",
                max_iterations=self.max_iterations,
                num_candidate_patches=self.num_candidate_patches,
            )

            # Run the coordinator
            final_patch_content = coordinator.run(
                issue_description=issue,
                task_id=None,
            )

            logger.info("=" * 80)
            logger.info("HARMONY MAS COMPLETED")
            logger.info("=" * 80)

            # Check if we got a valid result
            if final_patch_content and not final_patch_content.startswith("ERROR:"):
                return {
                    "success": True,
                    "final_patch": final_patch_content,
                    "state": coordinator.state,  # Access the state object
                }
            else:
                return {
                    "success": False,
                    "error": final_patch_content or "No patch generated",
                }

        except Exception as e:
            logger.error(f"Harmony MAS failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }

    def extract_patch_from_result(self, harmony_result: Dict) -> Optional[str]:
        """Extract the generated patch from Harmony MAS result.

        Args:
            harmony_result: Result from run_harmony_mas

        Returns:
            Patch content as string, or None if extraction failed
        """
        if not harmony_result.get("success"):
            logger.error("Cannot extract patch from failed Harmony MAS run")
            return None

        try:
            # The final_patch is directly in the result
            patch_content = harmony_result.get("final_patch")
            if not patch_content:
                logger.error("No final_patch in Harmony result")
                return None

            logger.info(f"✅ Extracted patch ({len(patch_content)} chars)")
            return patch_content

        except Exception as e:
            logger.error(f"Failed to extract patch: {e}", exc_info=True)
            return None

    def submit_to_defects4c(self, patch_content: str) -> Dict:
        """Submit patch to Defects4C for verification.

        Args:
            patch_content: The patch content to submit

        Returns:
            Verification result from Defects4C
        """
        logger.info("Submitting patch to Defects4C for verification...")

        # Step 1: Build patch
        logger.info("Step 1: Building patch...")
        patch_payload = {
            "bug_id": self.bug_id,
            "llm_response": patch_content,
            "method": "direct",
            "generate_diff": True,
            "persist_flag": True,
        }

        try:
            patch_response = requests.post(
                f"{DEFECTS4C_BASE_URL}/build_patch",
                headers={"Content-Type": "application/json"},
                json=patch_payload,
                timeout=60,
            )
            patch_data = patch_response.json()

            if not patch_data.get("success"):
                logger.error(f"Failed to build patch: {patch_data}")
                return {
                    "success": False,
                    "error": "Patch build failed",
                    "details": patch_data,
                }

            patch_path = patch_data.get("fix_p")
            logger.info(f"✅ Patch built: {patch_path}")

            # Step 2: Submit for verification
            logger.info("Step 2: Submitting for verification...")
            fix_payload = {
                "bug_id": self.bug_id,
                "patch_path": patch_path,
            }

            fix_response = requests.post(
                f"{DEFECTS4C_BASE_URL}/fix2",
                headers={"Content-Type": "application/json"},
                json=fix_payload,
                timeout=60,
            )
            fix_data = fix_response.json()
            handle = fix_data.get("handle")

            if not handle:
                logger.error(f"No handle returned: {fix_data}")
                return {
                    "success": False,
                    "error": "No verification handle",
                    "details": fix_data,
                }

            logger.info(f"✅ Verification submitted, handle: {handle}")

            # Step 3: Wait for results
            logger.info("Step 3: Waiting for verification results...")
            verification_result = self._wait_for_verification(handle)

            return verification_result

        except Exception as e:
            logger.error(f"Failed to submit to Defects4C: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }

    def _wait_for_verification(
        self, handle: str, max_wait: int = 300, poll_interval: int = 10
    ) -> Dict:
        """Wait for verification to complete.

        Args:
            handle: Verification handle
            max_wait: Maximum wait time in seconds
            poll_interval: Polling interval in seconds

        Returns:
            Verification result
        """
        start_time = time.time()

        while time.time() - start_time < max_wait:
            try:
                response = requests.get(f"{DEFECTS4C_BASE_URL}/status/{handle}", timeout=30)
                status_data = response.json()

                status = status_data.get("status", "unknown")
                logger.info(f"Verification status: {status}")

                if status == "completed":
                    fix_status = status_data.get("fix_status")
                    if fix_status == "success":
                        logger.info("✅ Verification PASSED!")
                    else:
                        logger.warning(f"❌ Verification FAILED: {status_data.get('fix_msg', 'Unknown error')}")

                    return {
                        "success": fix_status == "success",
                        "status": status,
                        "fix_status": fix_status,
                        "details": status_data,
                    }

                time.sleep(poll_interval)

            except Exception as e:
                logger.error(f"Error polling status: {e}")
                time.sleep(poll_interval)

        logger.error("Verification timeout")
        return {
            "success": False,
            "error": "Verification timeout",
            "status": "timeout",
        }

    def run_full_test(self) -> Dict:
        """Run the complete end-to-end test.

        Returns:
            Dictionary containing all test results
        """
        results = {
            "bug_id": self.bug_id,
            "timestamp": datetime.now().isoformat(),
            "stages": {},
        }

        try:
            # Stage 1: Fetch bug info
            logger.info("\n" + "=" * 80)
            logger.info("STAGE 1: FETCH BUG INFORMATION")
            logger.info("=" * 80)
            bug_data = self.fetch_bug_info()
            results["stages"]["fetch_bug_info"] = {"success": True, "data": bug_data}

            # Stage 2: Clone repository
            logger.info("\n" + "=" * 80)
            logger.info("STAGE 2: CLONE REPOSITORY")
            logger.info("=" * 80)
            repo_path = self.clone_repository()
            results["stages"]["clone_repository"] = {"success": True, "repo_path": str(repo_path)}

            # Stage 3: Construct issue
            logger.info("\n" + "=" * 80)
            logger.info("STAGE 3: CONSTRUCT ISSUE DESCRIPTION")
            logger.info("=" * 80)
            issue = self.construct_issue_description(bug_data)
            results["stages"]["construct_issue"] = {"success": True, "issue": issue}

            # Stage 4: Run Harmony MAS
            logger.info("\n" + "=" * 80)
            logger.info("STAGE 4: RUN HARMONY MAS")
            logger.info("=" * 80)
            harmony_result = self.run_harmony_mas(repo_path, issue)
            results["stages"]["run_harmony_mas"] = {
                "success": harmony_result.get("success"),
                "error": harmony_result.get("error"),
            }

            if not harmony_result.get("success"):
                results["overall_success"] = False
                results["error"] = "Harmony MAS failed"
                return results

            # Stage 5: Extract patch
            logger.info("\n" + "=" * 80)
            logger.info("STAGE 5: EXTRACT PATCH")
            logger.info("=" * 80)
            patch_content = self.extract_patch_from_result(harmony_result)
            if not patch_content:
                results["overall_success"] = False
                results["error"] = "Failed to extract patch"
                return results

            results["stages"]["extract_patch"] = {"success": True, "patch_length": len(patch_content)}

            # Stage 6: Submit to Defects4C
            logger.info("\n" + "=" * 80)
            logger.info("STAGE 6: SUBMIT TO DEFECTS4C")
            logger.info("=" * 80)
            verification_result = self.submit_to_defects4c(patch_content)
            results["stages"]["verification"] = verification_result

            # Final result
            results["overall_success"] = verification_result.get("success", False)

            return results

        except Exception as e:
            logger.error(f"Test failed with exception: {e}", exc_info=True)
            results["overall_success"] = False
            results["error"] = str(e)
            return results

    def save_results(self, results: Dict):
        """Save test results to file.

        Args:
            results: Test results dictionary
        """
        result_file = self.results_dir / f"{self.bug_id.replace('/', '_').replace('@', '_')}_result.json"
        with open(result_file, "w") as f:
            json.dump(results, f, indent=2, default=str)

        logger.info(f"Results saved to {result_file}")

        # Print summary
        logger.info("\n" + "=" * 80)
        logger.info("TEST SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Bug ID: {results['bug_id']}")
        logger.info(f"Overall Success: {results.get('overall_success', False)}")

        if results.get("overall_success"):
            logger.info("✅ TEST PASSED - Bug successfully fixed!")
        else:
            logger.warning(f"❌ TEST FAILED - {results.get('error', 'Unknown error')}")

        logger.info("=" * 80)


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
        help='Bug ID in format "project@commit_sha"',
    )

    parser.add_argument(
        "--work_dir",
        type=str,
        default="work/defects4c",
        help="Working directory for repos and results",
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
        "--num_candidate_patches",
        type=int,
        default=3,
        help="Number of candidate patches to generate",
    )

    parser.add_argument(
        "--docker_image",
        type=str,
        default="python:3.11",
        help="Docker image to use",
    )

    args = parser.parse_args()

    # Create integration instance
    integration = Defects4CIntegration(
        bug_id=args.bug_id,
        work_dir=Path(args.work_dir),
        coordinator_config=Path(args.coordinator_config),
        max_iterations=args.max_iterations,
        num_candidate_patches=args.num_candidate_patches,
        docker_image=args.docker_image,
    )

    # Run the test
    results = integration.run_full_test()

    # Save results
    integration.save_results(results)

    # Exit with appropriate code
    return 0 if results.get("overall_success") else 1


if __name__ == "__main__":
    sys.exit(main())
