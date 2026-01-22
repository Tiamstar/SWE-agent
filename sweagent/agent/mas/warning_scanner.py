"""Warning Scanner Module for Harmony MAS.

This module executes cppcheck scans on C/C++ repositories and parses
the results into structured WarningItem objects.
"""

from __future__ import annotations

import re
from pathlib import Path

from sweagent.environment.swe_env import SWEEnv
from sweagent.utils.log import get_logger

from .shared_state import WarningItem

logger = get_logger("harmony-warning-scanner", emoji="🔍")


class WarningScanner:
    """Executes cppcheck scans and parses warnings."""

    def __init__(self, env: SWEEnv, cppcheck_version: str = "auto"):
        """Initialize warning scanner.

        Args:
            env: SWEEnv instance (container already started)
            cppcheck_version: cppcheck version or "auto" to detect
        """
        self.env = env
        self.cppcheck_version = cppcheck_version
        self.cppcheck_available = self._check_cppcheck_availability()

    def _check_cppcheck_availability(self) -> bool:
        """Check if cppcheck is installed in the container.

        Returns:
            True if cppcheck is available
        """
        try:
            result = self.env.communicate("which cppcheck")
            if result and "/cppcheck" in result:
                # Get version
                version_result = self.env.communicate("cppcheck --version")
                logger.info(f"cppcheck detected: {version_result.strip()}")
                return True
            else:
                logger.warning("cppcheck not found in container")
                return False
        except Exception as e:
            logger.warning(f"Failed to check cppcheck: {e}")
            return False

    def scan_repository(
        self,
        source_dirs: list[str] | None = None,
        max_warnings: int = 500,
    ) -> list[WarningItem]:
        """Execute cppcheck scan on repository.

        Args:
            source_dirs: Directories to scan (default: auto-detect common dirs)
            max_warnings: Maximum warnings to collect (default: 500)

        Returns:
            List of WarningItem objects
        """
        if not self.cppcheck_available:
            logger.error("cppcheck not available, cannot scan repository")
            return []

        # Auto-detect source directories if not provided
        if source_dirs is None:
            source_dirs = self._detect_source_directories()

        if not source_dirs:
            logger.info("No subdirectories found, will scan C/C++ files in current directory")
            # Use file pattern matching instead of scanning entire directory
            source_dirs = None  # Will be handled by _build_cppcheck_command

        if source_dirs:
            logger.info(f"Scanning directories: {', '.join(source_dirs)}")
        else:
            logger.info("Scanning *.c, *.cpp files in repository root (limited to 10 files)")

        # Execute scan with output to temp file to avoid pexpect timeout
        output = self._execute_cppcheck_scan(source_dirs)

        if not output:
            logger.warning("cppcheck scan produced no output")
            return []

        # Parse warnings
        warnings = self._parse_cppcheck_output(output, max_warnings)

        logger.info(f"Parsed {len(warnings)} warnings from scan")
        return warnings

    def _execute_cppcheck_scan(self, source_dirs: list[str] | None) -> str:
        """Execute cppcheck and return output, handling long execution time gracefully.

        Uses background execution + polling to avoid pexpect timeout (30s default).
        Even with output redirected to file, shell waits for command completion,
        causing pexpect timeout for long-running scans (>30s).

        Solution: Run cppcheck in background, return immediately, poll for completion.

        Args:
            source_dirs: Directories to scan

        Returns:
            cppcheck output as string
        """
        import time

        temp_file = "/tmp/cppcheck_output.txt"
        done_file = "/tmp/cppcheck_done.txt"

        # Clean up any previous run
        cleanup_cmd = f"rm -f {temp_file} {done_file}"
        self.env.communicate(cleanup_cmd)

        # Build cppcheck command that runs in BACKGROUND
        base_command = self._build_cppcheck_command(source_dirs, temp_file)

        # Wrap in background execution with completion marker
        # Key: Use & to run in background, shell returns immediately
        background_command = (
            f"({base_command} && echo 'SUCCESS' > {done_file} || echo 'FAILED' > {done_file}) & "
            f"echo 'STARTED'"
        )

        logger.info("Starting cppcheck scan in background...")
        logger.debug(f"Command: {background_command}")

        try:
            result = self.env.communicate(background_command)

            if "STARTED" not in result:
                logger.error(f"Failed to start cppcheck: {result}")
                return ""

            logger.info("cppcheck scan started in background")
        except Exception as e:
            logger.error(f"Failed to start cppcheck command: {e}")
            return ""

        # Poll for completion (max 180 seconds)
        max_wait = 180
        poll_interval = 2  # Check every 2 seconds

        logger.info(f"Waiting for scan completion (max {max_wait}s)...")

        for elapsed in range(0, max_wait, poll_interval):
            time.sleep(poll_interval)

            # Check if done file exists
            check_cmd = f"[ -f {done_file} ] && cat {done_file} || echo 'RUNNING'"
            status = self.env.communicate(check_cmd).strip()

            if status == "SUCCESS":
                logger.info(f"cppcheck scan completed successfully (took ~{elapsed}s)")
                break
            elif status == "FAILED":
                logger.error(f"cppcheck scan failed (took ~{elapsed}s)")
                # Continue to try reading partial output
                break
            elif elapsed % 10 == 0:  # Log progress every 10 seconds
                logger.debug(f"Scan still running... ({elapsed}s elapsed)")
        else:
            # Timeout reached
            logger.warning(f"Scan did not complete within {max_wait}s, reading partial output")

        # Check if output file exists and has content
        try:
            check_cmd = f"[ -f {temp_file} ] && wc -c {temp_file} || echo '0'"
            file_size = self.env.communicate(check_cmd).strip()

            # Parse file size (format: "12345 /tmp/file.txt" or "0")
            size_bytes = 0
            if file_size.startswith("0"):
                size_bytes = 0
            else:
                size_bytes = int(file_size.split()[0])

            logger.info(f"Output file size: {size_bytes} bytes")

            if size_bytes == 0:
                logger.warning("Output file is empty or doesn't exist")
                # Try to get error info
                error_cmd = "cppcheck --version 2>&1"
                version_check = self.env.communicate(error_cmd)
                logger.debug(f"cppcheck version check: {version_check}")
                return ""
        except Exception as e:
            logger.warning(f"Failed to check output file: {e}")
            return ""

        # Read output from temp file
        try:
            read_cmd = f"cat {temp_file}"
            output = self.env.communicate(read_cmd)

            logger.info(f"Read cppcheck output: {len(output)} chars")

            # Show first few lines for debugging
            lines = output.splitlines()[:5]
            if lines:
                logger.debug("First lines of output:")
                for line in lines:
                    logger.debug(f"  {line}")

            # Clean up temp files
            self.env.communicate(f"rm -f {temp_file} {done_file}")

            return output

        except Exception as e:
            logger.error(f"Failed to read cppcheck output: {e}")
            return ""

    def _detect_source_directories(self) -> list[str]:
        """Auto-detect common source directories in the repository.

        Returns:
            List of directory paths
        """
        # Common C/C++ project directory names
        common_dirs = [
            "src",
            "source",
            "lib",
            "include",
            "core",
            "module",
            "common",
        ]

        found_dirs = []
        try:
            # Check which directories exist
            for dir_name in common_dirs:
                result = self.env.communicate(f"[ -d {dir_name} ] && echo 'EXISTS' || echo 'NOT_FOUND'")
                if result and "EXISTS" in result:
                    found_dirs.append(dir_name)

            if found_dirs:
                logger.info(f"Auto-detected source directories: {', '.join(found_dirs)}")
        except Exception as e:
            logger.warning(f"Failed to auto-detect directories: {e}")

        return found_dirs

    def _build_cppcheck_command(self, source_dirs: list[str] | None, output_file: str) -> str:
        """Build cppcheck command with appropriate flags.

        Design philosophy:
        - Prioritize EFFECTIVE scanning over speed
        - temp file architecture prevents pexpect timeout regardless of output size
        - Let Python code control warning count, not shell commands

        Args:
            source_dirs: Directories to scan, or None for file pattern matching
            output_file: File path to redirect output

        Returns:
            cppcheck command string with output redirection
        """
        # Build file/directory targets
        if source_dirs:
            # Hierarchical structure: scan all specified directories recursively
            targets = ' '.join(source_dirs)
            logger.info(f"Scanning directory targets: {targets}")
        else:
            # Flat structure: scan with depth limit to balance coverage and speed
            # maxdepth 2: root + one level of subdirectories (covers most important code)
            # Limit to 100 files: reasonable scan time while covering main codebase
            targets = "$(find . -maxdepth 2 -type f \\( -name '*.c' -o -name '*.cpp' -o -name '*.h' -o -name '*.hpp' \\) 2>/dev/null | head -100)"
            logger.info("Scanning up to 100 files (root + subdirectories, maxdepth 2)")

        # Build cppcheck command with effective scanning flags
        # Key design decisions:
        # 1. Timeout: 180s (3 minutes) - sufficient for most repos
        # 2. Comprehensive checks: warning, style, performance, portability
        # 3. No --max-configs limit (thorough analysis)
        # 4. Single thread (-j1) for cleaner, predictable output
        # 5. Correct redirect order: > file 2>&1 (NOT 2>&1 > file)
        # 6. Will be wrapped in background execution by caller
        command = (
            f"timeout 180 cppcheck "  # 3 minutes max
            "--enable=warning,style,performance,portability "  # Comprehensive checks
            "--language=c++ "
            "--inline-suppr "  # Allow inline suppressions in code
            "--suppress=missingIncludeSystem "  # Suppress system include warnings
            "--suppress=unusedFunction "  # Suppress unused function warnings
            "-j1 "  # Single thread for cleaner output
            "--template='{file}:{line}:{severity}:{message}' "  # Consistent format
            f"{targets} "
            f"> {output_file} 2>&1"  # Redirect stdout and stderr to file
        )

        return command

    def _parse_cppcheck_output(self, output: str, max_warnings: int) -> list[WarningItem]:
        """Parse cppcheck output into WarningItem objects.

        Expected format:
            file.c:142:warning:Potential null pointer dereference

        Args:
            output: Raw cppcheck output
            max_warnings: Maximum warnings to parse

        Returns:
            List of WarningItem objects (excludes 'information' and 'debug' severity)
        """
        warnings = []

        # Pattern: file:line:severity:message
        pattern = r"^(.+?):(\d+):(\w+):(.+)$"

        # Severity levels to include (exclude information, debug, note)
        valid_severities = {"warning", "error", "style", "performance", "portability"}

        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue

            match = re.match(pattern, line)
            if match:
                file_path, line_num, severity, message = match.groups()

                # Filter out meta-information (information, debug, note)
                if severity.lower() not in valid_severities:
                    logger.debug(f"Skipping non-warning severity '{severity}': {line}")
                    continue

                # Skip line 0 warnings (usually meta-information)
                if int(line_num) == 0:
                    logger.debug(f"Skipping line 0 warning (meta-information): {line}")
                    continue

                # Create WarningItem
                warning = WarningItem(
                    id=f"warning_{len(warnings) + 1:03d}",
                    file_path=file_path,
                    line_number=int(line_num),
                    severity=severity,
                    message=message.strip(),
                    raw_output=line,
                )

                warnings.append(warning)

                # Stop if we've reached max_warnings
                if len(warnings) >= max_warnings:
                    logger.info(f"Reached max_warnings limit ({max_warnings}), stopping parse")
                    break

        return warnings
