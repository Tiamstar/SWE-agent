#!/usr/bin/env python3
"""
Get ground truth patch for a Defects4C bug.

This script fetches the correct fix for a bug from the git repository.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_bug_id(bug_id: str) -> tuple[str, str, str]:
    """Parse bug_id into owner, repo, and commit.

    Args:
        bug_id: Bug ID in format "owner___repo@commit_sha"

    Returns:
        Tuple of (owner, repo, commit_sha)
    """
    if "@" not in bug_id or "___" not in bug_id:
        raise ValueError(f"Invalid bug_id format: {bug_id}")

    project_part, commit_sha = bug_id.split("@")
    owner, repo = project_part.split("___")

    return owner, repo, commit_sha


def get_ground_truth_patch(bug_id: str, file_path: str = None) -> str:
    """Get the ground truth patch for a bug.

    Args:
        bug_id: Bug ID in format "owner___repo@commit_sha"
        file_path: Optional specific file to show (e.g., "lib/preprocessor.cpp")

    Returns:
        The git diff showing the fix
    """
    owner, repo, commit_sha = parse_bug_id(bug_id)
    github_url = f"https://github.com/{owner}/{repo}.git"

    print(f"📥 Fetching ground truth patch for: {bug_id}")
    print(f"   Repository: {owner}/{repo}")
    print(f"   Commit: {commit_sha}")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "repo"

        # Clone the repository
        print("⏳ Cloning repository (this may take a while)...")
        result = subprocess.run(
            ["git", "clone", "--quiet", github_url, str(repo_dir)],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"❌ Error cloning repository: {result.stderr}")
            return None

        print("✅ Repository cloned")

        # Get the commit diff
        print(f"📋 Extracting patch from commit {commit_sha}...")

        cmd = ["git", "show", commit_sha]
        if file_path:
            cmd.append(file_path)

        result = subprocess.run(
            cmd,
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"❌ Error getting commit: {result.stderr}")
            return None

        return result.stdout


def main():
    parser = argparse.ArgumentParser(
        description="Get ground truth patch for a Defects4C bug"
    )
    parser.add_argument(
        "--bug_id",
        required=True,
        help='Bug ID in format "owner___repo@commit_sha"',
    )
    parser.add_argument(
        "--file",
        help="Specific file to show (e.g., lib/preprocessor.cpp)",
    )
    parser.add_argument(
        "--output",
        help="Output file path (default: print to stdout)",
    )
    parser.add_argument(
        "--diff-only",
        action="store_true",
        help="Show only the diff part (without commit message)",
    )

    args = parser.parse_args()

    # Get the patch
    patch_content = get_ground_truth_patch(args.bug_id, args.file)

    if patch_content is None:
        print("\n❌ Failed to get ground truth patch")
        sys.exit(1)

    # Process the patch if needed
    if args.diff_only:
        # Extract only the diff part
        lines = patch_content.split("\n")
        diff_start = None
        for i, line in enumerate(lines):
            if line.startswith("diff --git"):
                diff_start = i
                break

        if diff_start is not None:
            patch_content = "\n".join(lines[diff_start:])

    # Output the patch
    print("\n" + "=" * 80)
    print("GROUND TRUTH PATCH")
    print("=" * 80)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(patch_content)
        print(f"✅ Patch saved to: {args.output}")
        print()
    else:
        print(patch_content)
        print()

    print("=" * 80)


if __name__ == "__main__":
    main()
