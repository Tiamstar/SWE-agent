#!/usr/bin/env python3
"""List available Defects4C test cases.

This script helps you browse and select test cases from the Defects4C benchmark.
"""

import argparse
import json
from pathlib import Path
from typing import List, Dict


def list_projects(base_path: Path) -> List[str]:
    """List all available projects."""
    projects_dir = base_path / "defectsc_tpl" / "projects_v1"
    if not projects_dir.exists():
        return []

    projects = []
    for item in projects_dir.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            projects.append(item.name)

    return sorted(projects)


def list_bugs_for_project(base_path: Path, project: str, limit: int = None) -> List[Dict]:
    """List bugs for a specific project."""
    bugs_file = base_path / "defectsc_tpl" / "projects_v1" / project / "bugs_list_new.json"

    if not bugs_file.exists():
        return []

    with open(bugs_file) as f:
        bugs = json.load(f)

    if limit:
        bugs = bugs[:limit]

    return bugs


def format_bug_info(project: str, bug: Dict, index: int = None) -> str:
    """Format bug information for display."""
    commit = bug["commit_after"]
    bug_id = f"{project}@{commit}"
    bug_type = bug.get("type", {}).get("name", "Unknown")
    bug_category = bug.get("type", {}).get("id", "Unknown")
    date = bug.get("commit_date", "Unknown")
    files = bug.get("files", {})
    src_files = files.get("src", [])
    test_files = files.get("test", [])

    lines = []
    if index is not None:
        lines.append(f"\n{'='*70}")
        lines.append(f"Bug #{index}")
        lines.append(f"{'='*70}")

    lines.extend([
        f"Bug ID: {bug_id}",
        f"Type: {bug_type} (Category: {bug_category})",
        f"Date: {date}",
        f"Source files: {', '.join(src_files)}",
        f"Test files: {', '.join(test_files)}",
    ])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Browse Defects4C test cases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--base_path",
        type=str,
        default="defects4c-master",
        help="Base path to Defects4C directory",
    )

    parser.add_argument(
        "--project",
        type=str,
        help="Show bugs for specific project (e.g., danmar___cppcheck)",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Limit number of bugs to show per project",
    )

    parser.add_argument(
        "--category",
        type=str,
        help="Filter by bug category (e.g., 'B', 'D.1')",
    )

    parser.add_argument(
        "--simple",
        action="store_true",
        help="Show simple bugs only (single file, single function)",
    )

    args = parser.parse_args()

    base_path = Path(args.base_path)

    if not base_path.exists():
        print(f"Error: Defects4C directory not found at {base_path}")
        print("Please ensure defects4c-master directory exists")
        return 1

    # List projects
    if not args.project:
        print("Available Projects:")
        print("=" * 70)
        projects = list_projects(base_path)

        if not projects:
            print("No projects found")
            return 1

        for i, project in enumerate(projects, 1):
            bugs = list_bugs_for_project(base_path, project, limit=1)
            bug_count = len(list_bugs_for_project(base_path, project))
            print(f"{i:2d}. {project:40s} ({bug_count} bugs)")

        print("\nTo see bugs for a project, use:")
        print(f"  python {__file__} --project <project_name>")
        print("\nRecommended projects for testing:")
        print("  - danmar___cppcheck (static analysis tool)")
        print("  - fmtlib___fmt (formatting library)")
        print("  - CLIUtils___CLI11 (CLI parsing library)")
        return 0

    # List bugs for specific project
    bugs = list_bugs_for_project(base_path, args.project)

    if not bugs:
        print(f"No bugs found for project: {args.project}")
        return 1

    # Filter bugs
    filtered_bugs = bugs

    if args.category:
        filtered_bugs = [b for b in filtered_bugs if b.get("type", {}).get("id") == args.category]

    if args.simple:
        filtered_bugs = [
            b
            for b in filtered_bugs
            if len(b.get("files", {}).get("src", [])) == 1
            and b.get("files", {}).get("src0_location", {}).get("func_is_single", False)
        ]

    # Apply limit
    if args.limit:
        filtered_bugs = filtered_bugs[: args.limit]

    print(f"\nBugs for project: {args.project}")
    print(f"Total bugs: {len(bugs)}, Showing: {len(filtered_bugs)}")

    for i, bug in enumerate(filtered_bugs, 1):
        print(format_bug_info(args.project, bug, i))

    print("\n" + "=" * 70)
    print("To test a bug with Harmony MAS, use:")
    print(f'  python tools/test_harmony_with_defects4c.py --bug_id "<bug_id>"')
    print("\nExample:")
    if filtered_bugs:
        example_bug = filtered_bugs[0]
        example_id = f"{args.project}@{example_bug['commit_after']}"
        print(f'  python tools/test_harmony_with_defects4c.py --bug_id "{example_id}"')

    return 0


if __name__ == "__main__":
    exit(main())
