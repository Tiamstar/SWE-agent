#!/usr/bin/env python3
"""
Script to clone repositories at their pre-PR commit state.

For each PR, this script:
1. Extracts repository and PR information from the URL
2. Clones the repository
3. Fetches the PR branch
4. Finds the merge base (the commit before the PR changes)
5. Creates a branch at that commit for analysis
"""

import subprocess
import re
import sys
from pathlib import Path
from typing import Dict, Optional
import json


class PRBaseExtractor:
    def __init__(self, output_dir: str = "pr_base_repos"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.results = []

    def parse_pr_url(self, pr_url: str) -> Optional[Dict[str, str]]:
        """
        Parse GitCode PR URL to extract repository and PR information.

        Example URL: https://gitcode.com/openharmony/distributeddatamgr_relational_store/pull/2983
        """
        pattern = r'https://gitcode\.com/([^/]+)/([^/]+)/pull/(\d+)'
        match = re.match(pattern, pr_url)

        if not match:
            print(f"❌ Invalid PR URL format: {pr_url}")
            return None

        org, repo, pr_number = match.groups()

        return {
            'org': org,
            'repo': repo,
            'pr_number': pr_number,
            'clone_url': f'https://gitcode.com/{org}/{repo}.git',
            'pr_url': pr_url
        }

    def run_command(self, cmd: list, cwd: Optional[Path] = None, capture_output: bool = True) -> subprocess.CompletedProcess:
        """Run a shell command and return the result."""
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=capture_output,
                text=True,
                check=True
            )
            return result
        except subprocess.CalledProcessError as e:
            print(f"❌ Command failed: {' '.join(cmd)}")
            print(f"   Error: {e.stderr}")
            raise

    def get_pr_info_from_git(self, repo_path: Path, pr_number: str) -> Optional[Dict[str, str]]:
        """
        Fetch PR information using git commands.
        This fetches the PR as a local branch and gets its details.
        """
        # GitCode uses GitLab-style refs/merge-requests/NUMBER/head
        fetch_refs = [
            f'merge-requests/{pr_number}/head:pr-{pr_number}',  # GitLab/GitCode style
            f'pull/{pr_number}/head:pr-{pr_number}',            # GitHub style (fallback)
        ]

        fetched = False
        for fetch_ref in fetch_refs:
            try:
                print(f"  📥 Fetching PR #{pr_number} using {fetch_ref.split(':')[0]}...")
                self.run_command(
                    ['git', 'fetch', 'origin', fetch_ref],
                    cwd=repo_path
                )
                fetched = True
                print(f"  ✅ Successfully fetched PR using {fetch_ref.split(':')[0]}")
                break
            except subprocess.CalledProcessError:
                continue

        if not fetched:
            print(f"  ❌ Failed to fetch PR #{pr_number} using any known reference format")
            return None

        try:
            # Get the default branch (usually master or main)
            result = self.run_command(
                ['git', 'symbolic-ref', 'refs/remotes/origin/HEAD'],
                cwd=repo_path
            )
            default_branch = result.stdout.strip().replace('refs/remotes/origin/', '')

            # Get the merge base (the commit where the PR branch diverged)
            result = self.run_command(
                ['git', 'merge-base', f'pr-{pr_number}', f'origin/{default_branch}'],
                cwd=repo_path
            )
            base_commit = result.stdout.strip()

            # Get the head commit of the PR
            result = self.run_command(
                ['git', 'rev-parse', f'pr-{pr_number}'],
                cwd=repo_path
            )
            head_commit = result.stdout.strip()

            # Get commit message for verification
            result = self.run_command(
                ['git', 'log', '-1', '--format=%s', base_commit],
                cwd=repo_path
            )
            base_commit_msg = result.stdout.strip()

            return {
                'default_branch': default_branch,
                'base_commit': base_commit,
                'head_commit': head_commit,
                'base_commit_message': base_commit_msg
            }

        except subprocess.CalledProcessError as e:
            print(f"  ❌ Failed to get PR info: {e}")
            return None

    def process_pr(self, pr_url: str) -> Optional[Dict]:
        """Process a single PR and clone the repository at the base commit."""
        print(f"\n{'='*80}")
        print(f"🔍 Processing: {pr_url}")
        print(f"{'='*80}")

        # Parse URL
        pr_info = self.parse_pr_url(pr_url)
        if not pr_info:
            return None

        repo_name = pr_info['repo']
        pr_number = pr_info['pr_number']

        # Create directory for this PR
        pr_dir = self.output_dir / f"{repo_name}_PR{pr_number}"

        # Clone repository if not exists
        if not pr_dir.exists():
            print(f"📦 Cloning repository: {pr_info['clone_url']}")
            try:
                self.run_command(['git', 'clone', pr_info['clone_url'], str(pr_dir)])
            except subprocess.CalledProcessError:
                print(f"❌ Failed to clone repository")
                return None
        else:
            print(f"📂 Repository already exists at: {pr_dir}")

        # Get PR information
        git_info = self.get_pr_info_from_git(pr_dir, pr_number)
        if not git_info:
            print(f"❌ Failed to get PR information")
            return None

        base_commit = git_info['base_commit']

        # Create a branch at the base commit
        base_branch_name = f"base-before-pr{pr_number}"
        print(f"🌿 Creating branch '{base_branch_name}' at base commit: {base_commit[:8]}")

        try:
            # Delete branch if it exists
            self.run_command(
                ['git', 'branch', '-D', base_branch_name],
                cwd=pr_dir
            )
        except:
            pass  # Branch doesn't exist, that's fine

        # Create new branch at base commit
        self.run_command(
            ['git', 'checkout', '-b', base_branch_name, base_commit],
            cwd=pr_dir
        )

        result = {
            'pr_url': pr_url,
            'repo_name': repo_name,
            'pr_number': pr_number,
            'clone_url': pr_info['clone_url'],
            'local_path': str(pr_dir.absolute()),
            'base_commit': base_commit,
            'base_commit_message': git_info['base_commit_message'],
            'head_commit': git_info['head_commit'],
            'default_branch': git_info['default_branch'],
            'base_branch_name': base_branch_name
        }

        print(f"\n✅ Success!")
        print(f"   📍 Base commit: {base_commit[:8]} - {git_info['base_commit_message']}")
        print(f"   📂 Local path: {pr_dir.absolute()}")
        print(f"   🌿 Branch: {base_branch_name}")

        self.results.append(result)
        return result

    def save_results(self):
        """Save results to a JSON file."""
        output_file = self.output_dir / "pr_base_commits.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        print(f"\n📄 Results saved to: {output_file}")

        # Also create a summary markdown file
        summary_file = self.output_dir / "SUMMARY.md"
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("# PR Base Commits Summary\n\n")
            for result in self.results:
                f.write(f"## {result['repo_name']} - PR #{result['pr_number']}\n\n")
                f.write(f"- **PR URL**: {result['pr_url']}\n")
                f.write(f"- **Base Commit**: `{result['base_commit']}`\n")
                f.write(f"- **Commit Message**: {result['base_commit_message']}\n")
                f.write(f"- **Local Path**: `{result['local_path']}`\n")
                f.write(f"- **Branch**: `{result['base_branch_name']}`\n")
                f.write(f"\n### To use this repository:\n")
                f.write(f"```bash\n")
                f.write(f"cd {result['local_path']}\n")
                f.write(f"git checkout {result['base_branch_name']}\n")
                f.write(f"```\n\n")
                f.write(f"### To see the PR changes:\n")
                f.write(f"```bash\n")
                f.write(f"cd {result['local_path']}\n")
                f.write(f"git diff {result['base_commit']} {result['head_commit']}\n")
                f.write(f"```\n\n")
                f.write(f"---\n\n")

        print(f"📄 Summary saved to: {summary_file}")

    def print_summary(self):
        """Print a summary of all processed PRs."""
        print(f"\n{'='*80}")
        print(f"📊 SUMMARY")
        print(f"{'='*80}")
        print(f"Total PRs processed: {len(self.results)}")
        print(f"Output directory: {self.output_dir.absolute()}\n")

        for i, result in enumerate(self.results, 1):
            print(f"{i}. {result['repo_name']} PR#{result['pr_number']}")
            print(f"   Base: {result['base_commit'][:8]} - {result['base_commit_message'][:60]}")
            print(f"   Path: {result['local_path']}")
            print()


def main():
    # List of PR URLs
    pr_urls = [
        "https://gitcode.com/openharmony/distributeddatamgr_relational_store/pull/2983",
        "https://gitcode.com/openharmony/distributeddatamgr_relational_store/pull/3002",
        "https://gitcode.com/openharmony/communication_netstack/pull/2205",
        "https://gitcode.com/openharmony/arkui_ace_engine/pull/79534",
        "https://gitcode.com/openharmony/distributedhardware_distributed_hardware_fwk/pull/1163",
    ]

    extractor = PRBaseExtractor(output_dir="pr_base_repos")

    print("🚀 Starting PR base commit extraction...")
    print(f"📁 Output directory: {extractor.output_dir.absolute()}")

    for pr_url in pr_urls:
        try:
            extractor.process_pr(pr_url)
        except Exception as e:
            print(f"❌ Error processing {pr_url}: {e}")
            continue

    # Save results
    extractor.save_results()
    extractor.print_summary()

    print("\n✨ Done! You can now work with the pre-PR repository states.")


if __name__ == "__main__":
    main()
