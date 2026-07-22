"""Repository Management service layer.

Coordinates between the data-access layer, GitHub API client, and
Git operations. This is the sole authority over the repository lifecycle;
HTTP handlers must not call repositories or infra clients directly.

Background cloning pipeline:
    1. Validate URL format (done in schema).
    2. Check for duplicate (ConflictError if found and reclone=False).
    3. Persist PENDING record and return immediately.
    4. Background task: clone → extract metadata → mark READY / FAILED.
"""

import asyncio
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.exceptions import (
    RepositoryAlreadyExistsError,
    RepositoryNotFoundError,
)
from backend.app.core.logging import get_logger
from backend.app.infrastructure.git_client import clone_repository, remove_clone
from backend.app.infrastructure.github_client import GitHubClient, get_github_client
from backend.app.models.repository import Repository, RepositoryStatus
from backend.app.repositories.repository import RepositoryRepository
from backend.app.schemas.repository import (
    RepositoryCreateRequest,
    RepositoryCreateResponse,
    RepositoryListResponse,
    RepositoryResponse,
)

logger = get_logger(__name__)


class RepositoryService:
    """Orchestrates all repository management operations.

    Args:
        session: Injected SQLAlchemy async session.
        github_client: Optional :class:`~backend.app.infrastructure.github_client.GitHubClient`
                       override (used in tests to inject a mock).
    """

    def __init__(
        self,
        session: AsyncSession,
        github_client: GitHubClient | None = None,
    ) -> None:
        self._repo_repo = RepositoryRepository(session)
        self._github = github_client or get_github_client()

    # ── Public API ─────────────────────────────────────────────────────────────

    async def create_repository(
        self,
        request: RepositoryCreateRequest,
        *,
        background_tasks: asyncio.Task | None = None,
    ) -> RepositoryCreateResponse:
        """Register a new repository and enqueue background cloning.

        The method returns immediately with a PENDING status. All
        long-running operations (clone + metadata fetch) happen
        asynchronously via :meth:`_run_clone_pipeline`.

        Args:
            request: Validated :class:`~backend.app.schemas.repository.RepositoryCreateRequest`.
            background_tasks: Unused placeholder (FastAPI BackgroundTasks are
                              injected at the router level; this param is
                              kept for testability).

        Returns:
            :class:`~backend.app.schemas.repository.RepositoryCreateResponse`
            with the assigned UUID and ``PENDING`` status.

        Raises:
            RepositoryAlreadyExistsError: If the URL is already registered
                and ``request.reclone`` is ``False``.
        """
        github_url = request.github_url  # already normalised by schema validator

        logger.info(
            "Repository validation started",
            github_url=github_url,
        )

        existing = await self._repo_repo.get_by_github_url(github_url)

        if existing is not None:
            if not request.reclone:
                logger.info(
                    "Duplicate repository rejected",
                    github_url=github_url,
                    existing_id=str(existing.id),
                )
                raise RepositoryAlreadyExistsError(github_url)

            # reclone=True — reset the existing record to PENDING
            logger.info(
                "Re-clone requested; resetting existing repository",
                github_url=github_url,
                repository_id=str(existing.id),
            )
            if existing.local_path:
                await remove_clone(existing.local_path)

            await self._repo_repo.update_status(existing, RepositoryStatus.PENDING)
            return RepositoryCreateResponse(
                id=existing.id,
                status=RepositoryStatus.PENDING,
            )

        # New registration — derive owner/name from URL
        owner = request.parsed_owner
        name = request.parsed_name
        full_name = f"{owner}/{name}"

        repo = await self._repo_repo.create(
            owner=owner,
            name=name,
            full_name=full_name,
            github_url=github_url,
        )

        logger.info(
            "Repository record created, clone queued",
            repository_id=str(repo.id),
            full_name=full_name,
        )

        return RepositoryCreateResponse(
            id=repo.id,
            status=RepositoryStatus.PENDING,
        )

    async def run_clone_pipeline(self, repository_id: uuid.UUID) -> None:
        """Execute the full clone-and-metadata pipeline for a repository.

        Intended to be called from a FastAPI BackgroundTask or Celery worker.
        Manages all status transitions and error handling internally.

        Pipeline stages:
            1. Load repository record; set status → CLONING.
            2. Fetch metadata from GitHub REST API.
            3. Clone repository (shallow, depth=1).
            4. Persist clone metadata and GitHub metadata.
            5. Set status → READY.

        On any failure, status → FAILED and the partial clone is cleaned up.

        Args:
            repository_id: UUID of the repository to process.
        """
        # We need a fresh session for background execution (the request session
        # may have already closed).  We import here to avoid circular imports.
        from backend.app.db.session import get_session_context  # noqa: PLC0415

        async with get_session_context() as session:
            repo_repo = RepositoryRepository(session)
            repo = await repo_repo.get_by_id(repository_id)

            if repo is None:
                logger.error(
                    "run_clone_pipeline called for unknown repository",
                    repository_id=str(repository_id),
                )
                return

            await self._execute_pipeline(repo_repo, repo)

    async def get_repository(self, repository_id: uuid.UUID) -> RepositoryResponse:
        """Return the full detail view of a single repository.

        Args:
            repository_id: Target repository UUID.

        Returns:
            :class:`~backend.app.schemas.repository.RepositoryResponse`

        Raises:
            RepositoryNotFoundError: If no record exists for the given ID.
        """
        repo = await self._repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(str(repository_id))
        return RepositoryResponse.model_validate(repo)

    async def list_repositories(self) -> RepositoryListResponse:
        """Return a list of all registered repositories.

        Returns:
            :class:`~backend.app.schemas.repository.RepositoryListResponse`
        """
        repos = await self._repo_repo.list_all()
        items = [RepositoryResponse.model_validate(r) for r in repos]
        return RepositoryListResponse(items=items, total=len(items))

    async def delete_repository(self, repository_id: uuid.UUID) -> None:
        """Delete a repository record and its local clone.

        Args:
            repository_id: UUID of the repository to remove.

        Raises:
            RepositoryNotFoundError: If no record exists for the given ID.
        """
        repo = await self._repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(str(repository_id))

        local_path = repo.local_path
        full_name = repo.full_name

        # Remove database record first so we don't leave orphan records
        # if filesystem deletion fails (filesystem is more recoverable).
        await self._repo_repo.delete(repo)

        if local_path:
            logger.info(
                "Removing local clone",
                repository_id=str(repository_id),
                local_path=local_path,
            )
            await remove_clone(local_path)

        logger.info(
            "Repository deleted",
            repository_id=str(repository_id),
            full_name=full_name,
        )

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _execute_pipeline(
        self,
        repo_repo: RepositoryRepository,
        repo: Repository,
    ) -> None:
        """Internal pipeline: set CLONING, clone, fetch metadata, set READY.

        All exceptions are caught; status is set to FAILED on any error.

        Args:
            repo_repo: The data-access layer instance (owns the active session).
            repo: The repository ORM instance to process.
        """
        repository_id = repo.id
        github_url = repo.github_url
        owner = repo.owner
        name = repo.name

        # ── Stage 1: Transition to CLONING ───────────────────────────────────
        await repo_repo.update_status(repo, RepositoryStatus.CLONING)
        logger.info(
            "Repository cloning started",
            repository_id=str(repository_id),
            github_url=github_url,
        )

        try:
            # ── Stage 2: Fetch GitHub metadata ───────────────────────────────
            logger.info(
                "Fetching GitHub metadata",
                repository_id=str(repository_id),
                owner=owner,
                name=name,
            )
            metadata = await self._github.get_repository(owner, name)
            logger.info(
                "GitHub metadata fetched",
                repository_id=str(repository_id),
                default_branch=metadata.default_branch,
                language=metadata.language,
            )

            # ── Stage 3: Clone repository ─────────────────────────────────────
            logger.info(
                "Repository cloning started (git)",
                repository_id=str(repository_id),
                github_url=github_url,
            )
            clone_result = await clone_repository(
                github_url=github_url,
                repository_id=repository_id,
            )
            logger.info(
                "Clone completed",
                repository_id=str(repository_id),
                local_path=clone_result.local_path,
                current_commit=clone_result.current_commit[:8],
            )

            # ── Stage 4: Persist clone + GitHub metadata ───────────────────────
            await repo_repo.update_clone_metadata(
                repo,
                local_path=clone_result.local_path,
                current_commit=clone_result.current_commit,
                default_branch=clone_result.default_branch or metadata.default_branch,
                status=RepositoryStatus.READY,
            )
            await repo_repo.update_github_metadata(
                repo,
                description=metadata.description,
                visibility=metadata.visibility,
                language=metadata.language,
                stars=metadata.stars,
                forks=metadata.forks,
                default_branch=metadata.default_branch,
            )

            logger.info(
                "Database updated — repository READY",
                repository_id=str(repository_id),
                full_name=repo.full_name,
            )

        except Exception as exc:
            logger.error(
                "Repository pipeline failed",
                repository_id=str(repository_id),
                github_url=github_url,
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            await repo_repo.mark_failed(repo, reason=str(exc))
            # Re-raise so Celery / caller can observe the failure
            raise
