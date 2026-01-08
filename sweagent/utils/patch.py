"""Utilities for applying patches to local directories."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from sweagent.utils.log import get_logger

logger = get_logger("patch-utils", emoji="🩹")


def apply_patch_to_directory(
    patch_content: str,
    target_dir: Path,
    *,
    dry_run: bool = False,
    use_git: bool | None = None,
) -> tuple[bool, str]:
    """Apply a patch to a local directory.

    This function automatically detects whether the target directory is a git
    repository and uses the appropriate method to apply the patch:
    - Git repository: uses `git apply`
    - Non-git directory: uses `patch` command

    Args:
        patch_content: The patch content (git diff format)
        target_dir: The target directory to apply the patch to
        dry_run: If True, only check if the patch can be applied without actually applying it
        use_git: Force using git apply (True) or patch command (False). If None, auto-detect.

    Returns:
        Tuple of (success: bool, message: str)
    """
    target_dir = Path(target_dir).resolve()

    if not target_dir.exists():
        return False, f"Target directory does not exist: {target_dir}"

    # Auto-detect if directory is a git repo
    if use_git is None:
        use_git = (target_dir / ".git").exists()

    # Save patch to temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
        f.write(patch_content)
        patch_file = Path(f.name)

    try:
        if use_git:
            return _apply_with_git(patch_file, target_dir, dry_run=dry_run)
        else:
            return _apply_with_patch(patch_file, target_dir, dry_run=dry_run)
    finally:
        # Clean up temp file
        try:
            patch_file.unlink()
        except Exception:
            pass


def _apply_with_git(patch_file: Path, target_dir: Path, *, dry_run: bool) -> tuple[bool, str]:
    """Apply patch using git apply."""
    logger.info(f"Applying patch using git apply {'(dry-run)' if dry_run else ''}")

    cmd = ["git", "apply"]
    if dry_run:
        cmd.append("--check")
    cmd.append(str(patch_file))

    try:
        result = subprocess.run(
            cmd,
            cwd=target_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            if dry_run:
                return True, "Patch can be applied successfully (dry-run)"
            else:
                return True, "Patch applied successfully using git apply"
        else:
            error_msg = result.stderr or result.stdout or "Unknown error"
            return False, f"git apply failed: {error_msg}"

    except subprocess.TimeoutExpired:
        return False, "git apply timed out"
    except Exception as e:
        return False, f"git apply failed with exception: {e}"


def _apply_with_patch(patch_file: Path, target_dir: Path, *, dry_run: bool) -> tuple[bool, str]:
    """Apply patch using patch command."""
    logger.info(f"Applying patch using patch command {'(dry-run)' if dry_run else ''}")

    cmd = ["patch", "-p1"]
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend(["-i", str(patch_file)])

    try:
        result = subprocess.run(
            cmd,
            cwd=target_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            if dry_run:
                return True, "Patch can be applied successfully (dry-run)"
            else:
                return True, "Patch applied successfully using patch command"
        else:
            error_msg = result.stderr or result.stdout or "Unknown error"
            return False, f"patch command failed: {error_msg}"

    except subprocess.TimeoutExpired:
        return False, "patch command timed out"
    except FileNotFoundError:
        return False, "patch command not found. Please install patch utility."
    except Exception as e:
        return False, f"patch command failed with exception: {e}"


def save_patch_to_file(patch_content: str, output_path: Path) -> None:
    """Save patch content to a file.

    Args:
        patch_content: The patch content
        output_path: Where to save the patch file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(patch_content)
    logger.info(f"Patch saved to: {output_path}")
