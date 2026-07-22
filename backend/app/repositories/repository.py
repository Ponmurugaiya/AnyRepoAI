"""Data-access layer for the Repository aggregate root.

All database interactions for the ``repositories`` table are encapsulated
here. No business logic lives in this class — only query construction
and result hydration.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.models.repository import Repository, RepositoryStatus

logger = get_logger(__name__)


class RepositoryRepository:
    """Repository (data-access) class for the Repository aggregate.

    Args:
        session: An injected SQLAlchemy :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Read operations ───────────────────────────────────────────────────────

    async def get_by_id(self, repository_id: uuid.UUID) -> Repository | None:
        """Fetch a repository by its UUID primary key.

        Args:
            repository_id: The UUID of the repository to retrieve.

        Returns:
            The :class:`~backend.app.models.repository.Repository` instance,
            or ``None`` if not found.
        """
        result = await self._session.execute(
            select(Repository).where(Repository.id == repository_id)
        )
        return result.scalar_one_or_none()

    async def get_by_github_url(self, github_url: str) -> Repository | None:
        """Fetch a repository by its normalised GitHub URL.

        Args:
            github_url: The normalised HTTPS URL (no trailing ``.git``).

        Returns:
            The matching :class:`~backend.app.models.repository.Repository`,
            or ``None`` if not found.
        """
        result = await self._session.execute(
            select(Repository).where(Repository.github_url == github_url)
        )
        return result.scalar_one_or_none()

    async def get_by_full_name(self, full_name: str) -> Repository | None:
        """Fetch a repository by its ``owner/name`` full name.

        Args:
            full_name: The canonical ``owner/name`` string.

        Returns:
            The matching :class:`~backend.app.models.repository.Repository`,
            or ``None`` if not found.
        """
        result = await self._session.execute(
            select(Repository).where(Repository.full_name == full_name)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Repository]:
        """Return all registered repositories ordered by creation time (newest first).

        Returns:
            A list of :class:`~backend.app.models.repository.Repository` instances.
        """
        result = await self._session.execute(
            select(Repository).order_by(Repository.created_at.desc())
        )
        return list(result.scalars().all())

    # ── Write operations ──────────────────────────────────────────────────────

    async def create(
        self,
        *,
        owner: str,
        name: str,
        full_name: str,
        github_url: str,
    ) -> Repository:
        """Persist a new repository record in PENDING status.

        Args:
            owner: GitHub repository owner.
            name: Repository name (without owner).
            full_name: Canonical ``owner/name`` identifier.
            github_url: Normalised HTTPS URL.

        Returns:
            The newly created :class:`~backend.app.models.repository.Repository`.
        """
        repo = Repository(
            owner=owner,
            name=name,
            full_name=full_name,
            github_url=github_url,
            clone_status=RepositoryStatus.PENDING,
        )
        self._session.add(repo)
        await self._session.flush()  # Populate id / server defaults
        await self._session.refresh(repo)

        logger.info(
            "Repository record created",
            repository_id=str(repo.id),
            full_name=full_name,
        )
        return repo

    async def update_status(
        self,
        repository: Repository,
        status: RepositoryStatus,
    ) -> Repository:
        """Update only the ``clone_status`` field.

        Args:
            repository: The repository instance to update.
            status: The new status to apply.

        Returns:
            The updated repository instance.
        """
        repository.clone_status = status
        await self._session.flush()
        await self._session.refresh(repository)

        logger.debug(
            "Repository status updated",
            repository_id=str(repository.id),
            new_status=status.value,
        )
        return repository

    async def update_clone_metadata(
        self,
        repository: Repository,
        *,
        local_path: str,
        current_commit: str,
        default_branch: str,
        status: RepositoryStatus = RepositoryStatus.READY,
    ) -> Repository:
        """Persist post-clone filesystem metadata.

        Called by the background task after a successful ``git clone``.

        Args:
            repository: The repository instance to update.
            local_path: Absolute path to the cloned directory.
            current_commit: HEAD commit SHA.
            default_branch: Name of the default branch.
            status: Resulting status (default: ``READY``).

        Returns:
            The updated repository instance.
        """
        repository.local_path = local_path
        repository.current_commit = current_commit
        repository.default_branch = default_branch
        repository.clone_status = status
        await self._session.flush()
        await self._session.refresh(repository)

        logger.info(
            "Repository clone metadata persisted",
            repository_id=str(repository.id),
            local_path=local_path,
            current_commit=current_commit,
            default_branch=default_branch,
        )
        return repository

    async def update_github_metadata(
        self,
        repository: Repository,
        *,
        description: str | None,
        visibility: str | None,
        language: str | None,
        stars: int,
        forks: int,
        default_branch: str | None,
    ) -> Repository:
        """Persist metadata fetched from the GitHub REST API.

        Args:
            repository: The repository instance to update.
            description: Repository description.
            visibility: ``"public"`` or ``"private"``.
            language: Primary language.
            stars: Star count.
            forks: Fork count.
            default_branch: Default branch name.

        Returns:
            The updated repository instance.
        """
        repository.description = description
        repository.visibility = visibility
        repository.language = language
        repository.stars = stars
        repository.forks = forks
        repository.last_synced_at = datetime.now(timezone.utc)
        if default_branch:
            repository.default_branch = default_branch

        await self._session.flush()
        await self._session.refresh(repository)

        logger.info(
            "Repository GitHub metadata updated",
            repository_id=str(repository.id),
            stars=stars,
            forks=forks,
            language=language,
        )
        return repository

    async def mark_failed(
        self,
        repository: Repository,
        *,
        reason: str = "",
    ) -> Repository:
        """Set repository status to FAILED.

        Args:
            repository: The repository instance.
            reason: Optional human-readable failure reason (logged only).

        Returns:
            The updated repository instance.
        """
        repository.clone_status = RepositoryStatus.FAILED
        await self._session.flush()
        await self._session.refresh(repository)

        logger.error(
            "Repository marked as FAILED",
            repository_id=str(repository.id),
            reason=reason,
        )
        return repository

    async def delete(self, repository: Repository) -> None:
        """Delete a repository record from the database.

        Args:
            repository: The repository instance to remove.
        """
        await self._session.delete(repository)
        await self._session.flush()

        logger.info(
            "Repository record deleted",
            repository_id=str(repository.id),
            full_name=repository.full_name,
        )
