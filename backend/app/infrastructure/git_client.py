"""Git operations wrapper using GitPython.

Provides a single async-friendly interface for cloning repositories
and inspecting local clones. All blocking GitPython calls are executed
in a thread pool to avoid blocking the event loop.
"""

import asyncio
import shutil
import uuid
from pathlib import Path

import git
from git import GitCommandError, InvalidGitRepositoryError, Repo

from backend.app.core.config import get_settings
from backend.app.core.exceptions import RepositoryCloneError, RepositoryEmptyError
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


class CloneResult:
    """Value object returned after a successful clone operation.

    Attributes:
        local_path: Absolute path to the cloned directory.
        default_branch: Name of the default branch (HEAD ref).
        current_commit: Full SHA of the HEAD commit.
    """

    __slots__ = ("local_path", "default_branch", "current_commit")

    def __init__(self, *, local_path: str, default_branch: str, current_commit: str) -> None:
        self.local_path = local_path
        self.default_branch = default_branch
        self.current_commit = current_commit


def _resolve_clone_path(repository_id: uuid.UUID) -> Path:
    """Compute the filesystem path for a repository clone.

    The layout is ``{clone_root}/{repository_id}/``.

    Args:
        repository_id: The UUID of the repository record.

    Returns:
        :class:`~pathlib.Path` to the clone directory (not yet created).
    """
    settings = get_settings()
    return Path(settings.repository.clone_root) / str(repository_id)


def _clone_repository_sync(
    *,
    github_url: str,
    clone_path: Path,
    timeout: int,
) -> CloneResult:
    """Perform a shallow ``git clone`` synchronously (runs inside a thread).

    Uses ``depth=1`` to clone only the latest commit tree, minimising
    bandwidth and disk usage for large repositories.

    Args:
        github_url: The HTTPS URL to clone (no trailing ``.git``).
        clone_path: Target directory path (must not already exist).
        timeout: Maximum seconds before aborting the clone.

    Returns:
        :class:`CloneResult` with path, branch, and commit hash.

    Raises:
        RepositoryEmptyError: If the repository has no commits.
        RepositoryCloneError: For any other git failure.
    """
    logger.info(
        "Git clone started",
        github_url=github_url,
        clone_path=str(clone_path),
    )

    clone_url = github_url if github_url.endswith(".git") else f"{github_url}.git"

    try:
        repo: Repo = git.Repo.clone_from(
            clone_url,
            str(clone_path),
            depth=1,
            kill_after_timeout=timeout,
        )
    except GitCommandError as exc:
        error_msg = str(exc).lower()

        # Detect empty repository (no commits)
        if "remote: empty repository" in error_msg or "did not send all necessary objects" in error_msg:
            logger.warning("Repository is empty", github_url=github_url)
            # Clean up partial clone directory
            if clone_path.exists():
                shutil.rmtree(clone_path, ignore_errors=True)
            raise RepositoryEmptyError(github_url) from exc

        logger.error(
            "Git clone failed",
            github_url=github_url,
            error=str(exc),
        )
        # Clean up partial clone directory
        if clone_path.exists():
            shutil.rmtree(clone_path, ignore_errors=True)
        raise RepositoryCloneError(github_url, str(exc)) from exc

    # Extract HEAD commit and branch
    try:
        current_commit = repo.head.commit.hexsha
        # Prefer the symbolic ref name; fall back to 'main'
        try:
            default_branch = repo.active_branch.name
        except TypeError:
            # Detached HEAD state — use remote tracking ref
            remote_refs = repo.remotes[0].refs if repo.remotes else []
            default_branch = (
                remote_refs[0].remote_head
                if remote_refs
                else "main"
            )
    except (ValueError, IndexError, AttributeError) as exc:
        logger.error(
            "Failed to read HEAD after clone",
            github_url=github_url,
            error=str(exc),
        )
        if clone_path.exists():
            shutil.rmtree(clone_path, ignore_errors=True)
        raise RepositoryCloneError(github_url, f"HEAD ref unreadable: {exc}") from exc

    logger.info(
        "Git clone completed",
        github_url=github_url,
        clone_path=str(clone_path),
        default_branch=default_branch,
        current_commit=current_commit[:8],
    )

    return CloneResult(
        local_path=str(clone_path),
        default_branch=default_branch,
        current_commit=current_commit,
    )


async def clone_repository(
    *,
    github_url: str,
    repository_id: uuid.UUID,
) -> CloneResult:
    """Async entry-point for cloning a GitHub repository.

    Computes the clone path from ``{REPO_CLONE_ROOT}/{repository_id}/``,
    delegates the blocking git operation to a thread pool, and returns
    a :class:`CloneResult`.

    Args:
        github_url: Normalised HTTPS URL (without ``.git`` suffix).
        repository_id: The UUID of the repository DB record. Used to
                       derive the clone directory path.

    Returns:
        :class:`CloneResult` with all post-clone metadata.

    Raises:
        RepositoryEmptyError: If the repository contains no commits.
        RepositoryCloneError: For any other clone failure.
    """
    settings = get_settings()
    clone_path = _resolve_clone_path(repository_id)

    # Ensure parent directory exists
    clone_path.parent.mkdir(parents=True, exist_ok=True)

    loop = asyncio.get_event_loop()
    result: CloneResult = await loop.run_in_executor(
        None,
        lambda: _clone_repository_sync(
            github_url=github_url,
            clone_path=clone_path,
            timeout=settings.repository.clone_timeout,
        ),
    )
    return result


async def remove_clone(local_path: str) -> None:
    """Remove a cloned repository from the filesystem asynchronously.

    Silently succeeds if the path does not exist.

    Args:
        local_path: Absolute path to the cloned directory.
    """
    path = Path(local_path)
    if not path.exists():
        logger.debug("Clone path does not exist; nothing to remove", path=str(path))
        return

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: shutil.rmtree(str(path), ignore_errors=True),
    )
    logger.info("Clone directory removed", path=str(path))
