import asyncio
import os
from pathlib import Path
from typing import Any, Literal, Protocol

from git import InvalidGitRepositoryError
from git import Repo as GitRepo
from pydantic import BaseModel, ConfigDict, Field
from swerex.deployment.abstract import AbstractDeployment
from swerex.runtime.abstract import Command, UploadRequest
from typing_extensions import Self

from sweagent.utils.github import _parse_gh_repo_url
from sweagent.utils.log import get_logger

logger = get_logger("swea-config", emoji="🔧")


class Repo(Protocol):
    """Protocol for repository configurations."""

    base_commit: str
    repo_name: str

    def copy(self, deployment: AbstractDeployment): ...

    def get_reset_commands(self) -> list[str]: ...


def _get_git_reset_commands(base_commit: str) -> list[str]:
    return [
        "git fetch",
        "git status",
        "git restore .",
        "git reset --hard",
        f"git checkout {base_commit}",
        "git clean -fdq",
    ]


class PreExistingRepoConfig(BaseModel):
    """Use this to specify a repository that already exists on the deployment.
    This is important because we need to cd to the repo before running the agent.

    Note: The repository must be at the root of the deployment.
    """

    repo_name: str
    """The repo name (the repository must be located at the root of the deployment)."""
    base_commit: str = Field(default="HEAD")
    """The commit to reset the repository to. The default is HEAD,
    i.e., the latest commit. You can also set this to a branch name (e.g., `dev`),
    a tag (e.g., `v0.1.0`), or a commit hash (e.g., `a4464baca1f`).
    SWE-agent will then start from this commit when trying to solve the problem.
    """

    type: Literal["preexisting"] = "preexisting"
    """Discriminator for (de)serialization/CLI. Do not change."""

    reset: bool = True
    """If True, reset the repository to the base commit after the copy operation."""

    model_config = ConfigDict(extra="forbid")

    def copy(self, deployment: AbstractDeployment):
        """Does nothing."""
        pass

    def get_reset_commands(self) -> list[str]:
        """Issued after the copy operation or when the environment is reset."""
        if self.reset:
            return _get_git_reset_commands(self.base_commit)
        return []


class LocalRepoConfig(BaseModel):
    path: Path
    base_commit: str = Field(default="HEAD")
    """The commit to reset the repository to. The default is HEAD,
    i.e., the latest commit. You can also set this to a branch name (e.g., `dev`),
    a tag (e.g., `v0.1.0`), or a commit hash (e.g., `a4464baca1f`).
    SWE-agent will then start from this commit when trying to solve the problem.
    """

    skip_reset: bool = Field(default=False)
    """If True, skip git reset commands after copying the repository.
    This is useful when you want to preserve the exact state of the repository.
    """

    auto_init_git: bool = Field(default=True)
    """If True, automatically initialize git repository in container if source is not a git repo.
    This allows working with non-git directories by automatically setting up version control
    in the container environment.
    """

    type: Literal["local"] = "local"
    """Discriminator for (de)serialization/CLI. Do not change."""

    model_config = ConfigDict(extra="forbid")

    def __init__(self, **data):
        super().__init__(**data)
        # Internal flags to track repository state
        object.__setattr__(self, '_needs_git_init', False)
        object.__setattr__(self, '_is_original_git_repo', None)

    @property
    def repo_name(self) -> str:
        """Set automatically based on the repository name. Cannot be set."""
        return Path(self.path).resolve().name.replace(" ", "-").replace("'", "")

    # Let's not make this a model validator, because it leads to cryptic errors.
    # Let's just check during copy instead.
    def check_valid_repo(self) -> Self:
        """Check if the repository is valid and record its state.

        For Git repositories:
        - Requires clean working tree (no uncommitted changes)
        - Records that it's a Git repo

        For non-Git directories:
        - If auto_init_git=True, will be initialized in container
        - Records that it's not a Git repo
        """
        try:
            repo = GitRepo(self.path, search_parent_directories=False)
            # It's a Git repository
            object.__setattr__(self, '_is_original_git_repo', True)

            # Check for dirty state
            if repo.is_dirty() and "PYTEST_CURRENT_TEST" not in os.environ:
                msg = (
                    f"Git repository at {self.path} has uncommitted changes.\n"
                    f"This violates version control principles:\n"
                    f"  - Generated patches will be based on uncommitted state\n"
                    f"  - Patches may fail to apply if uncommitted changes are reverted\n"
                    f"  - Reproducibility is compromised\n\n"
                    f"Please commit or stash your changes first:\n"
                    f"  git add -A && git commit -m 'WIP: before AI fix'\n"
                    f"  # or\n"
                    f"  git stash"
                )
                raise ValueError(msg)

            logger.info(f"✓ Git repository at {self.path} is clean")

        except InvalidGitRepositoryError:
            # Not a git repository
            object.__setattr__(self, '_is_original_git_repo', False)

            if self.auto_init_git:
                logger.info(f"Directory {self.path} is not a git repository. Will initialize git in container.")
                object.__setattr__(self, '_needs_git_init', True)
            else:
                msg = f"Could not find git repository at {self.path=}."
                msg += "\nHint: Set auto_init_git=True to automatically initialize git in container."
                raise ValueError(msg)

        return self

    def copy(self, deployment: AbstractDeployment):
        self.check_valid_repo()
        asyncio.run(
            deployment.runtime.upload(UploadRequest(source_path=str(self.path), target_path=f"/{self.repo_name}"))
        )
        r = asyncio.run(
            deployment.runtime.execute(Command(command=f"chown -R root:root /{self.repo_name}", shell=True))
        )
        if r.exit_code != 0:
            msg = f"Failed to change permissions on copied repository (exit code: {r.exit_code}, stdout: {r.stdout}, stderr: {r.stderr})"
            raise RuntimeError(msg)

        # If the source directory was not a git repository, initialize it in the container
        if self._needs_git_init:
            logger.info(f"Initializing git repository in container at /{self.repo_name}")
            init_commands = [
                f"cd /{self.repo_name}",
                "git init",
                "git config user.name 'SWE-agent'",
                "git config user.email 'swe-agent@example.com'",
                "git add -A",
                "git commit -m 'Initial state' --allow-empty",
            ]
            r = asyncio.run(
                deployment.runtime.execute(
                    Command(command=" && ".join(init_commands), shell=True, timeout=60)
                )
            )
            if r.exit_code != 0:
                msg = f"Failed to initialize git repository in container (exit code: {r.exit_code}, stdout: {r.stdout}, stderr: {r.stderr})"
                raise RuntimeError(msg)
            logger.info("Git repository initialized successfully in container")

    def get_reset_commands(self) -> list[str]:
        """Issued after the copy operation or when the environment is reset."""
        # If git was auto-initialized in container, no need to reset
        # (it's already at initial state)
        if self._needs_git_init:
            logger.info("Skipping git reset commands (auto-initialized git repository)")
            return []

        # If skip_reset is True, don't run git commands
        if self.skip_reset:
            logger.info("Skipping git reset commands (skip_reset=True)")
            return []

        return _get_git_reset_commands(self.base_commit)

    @property
    def is_original_git_repo(self) -> bool:
        """Check if the original source directory was a Git repository.

        This is used by patch application logic to determine whether to use
        git apply or patch command when applying changes back to the local directory.

        Returns:
            True if original directory was a Git repo, False if it was a plain directory
        """
        if self._is_original_git_repo is None:
            # Not yet checked, do it now
            try:
                GitRepo(self.path, search_parent_directories=False)
                return True
            except InvalidGitRepositoryError:
                return False
        return self._is_original_git_repo


class GithubRepoConfig(BaseModel):
    github_url: str

    base_commit: str = Field(default="HEAD")
    """The commit to reset the repository to. The default is HEAD,
    i.e., the latest commit. You can also set this to a branch name (e.g., `dev`),
    a tag (e.g., `v0.1.0`), or a commit hash (e.g., `a4464baca1f`).
    SWE-agent will then start from this commit when trying to solve the problem.
    """

    clone_timeout: float = 500
    """Timeout for git clone operation."""

    type: Literal["github"] = "github"
    """Discriminator for (de)serialization/CLI. Do not change."""

    model_config = ConfigDict(extra="forbid")

    def model_post_init(self, __context: Any) -> None:
        if self.github_url.count("/") == 1:
            self.github_url = f"https://github.com/{self.github_url}"

    @property
    def repo_name(self) -> str:
        org, repo = _parse_gh_repo_url(self.github_url)
        return f"{org}__{repo}"

    def _get_url_with_token(self, token: str) -> str:
        """Prepend github token to URL"""
        if not token:
            return self.github_url
        if "@" in self.github_url:
            logger.warning("Cannot prepend token to URL. '@' found in URL")
            return self.github_url
        _, _, url_no_protocol = self.github_url.partition("://")
        return f"https://{token}@{url_no_protocol}"

    def copy(self, deployment: AbstractDeployment):
        """Clones the repository to the sandbox."""
        base_commit = self.base_commit
        github_token = os.getenv("GITHUB_TOKEN", "")
        url = self._get_url_with_token(github_token)
        asyncio.run(
            deployment.runtime.execute(
                Command(
                    command=" && ".join(
                        (
                            f"mkdir /{self.repo_name}",
                            f"cd /{self.repo_name}",
                            "git init",
                            f"git remote add origin {url}",
                            f"git fetch --depth 1 origin {base_commit}",
                            "git checkout FETCH_HEAD",
                            "cd ..",
                        )
                    ),
                    timeout=self.clone_timeout,
                    shell=True,
                    check=True,
                )
            ),
        )

    def get_reset_commands(self) -> list[str]:
        """Issued after the copy operation or when the environment is reset."""
        return _get_git_reset_commands(self.base_commit)


RepoConfig = LocalRepoConfig | GithubRepoConfig | PreExistingRepoConfig


def repo_from_simplified_input(
    *, input: str, base_commit: str = "HEAD", type: Literal["local", "github", "preexisting", "auto"] = "auto"
) -> RepoConfig:
    """Get repo config from a simplified input.

    Args:
        input: Local path or GitHub URL
        type: The type of repo. Set to "auto" to automatically detect the type
            (does not work for preexisting repos).
    """
    if type == "local":
        return LocalRepoConfig(path=Path(input), base_commit=base_commit)
    if type == "github":
        return GithubRepoConfig(github_url=input, base_commit=base_commit)
    if type == "preexisting":
        return PreExistingRepoConfig(repo_name=input, base_commit=base_commit)
    if type == "auto":
        if input.startswith("https://github.com/"):
            return GithubRepoConfig(github_url=input, base_commit=base_commit)
        else:
            return LocalRepoConfig(path=Path(input), base_commit=base_commit)
    msg = f"Unknown repo type: {type}"
    raise ValueError(msg)
