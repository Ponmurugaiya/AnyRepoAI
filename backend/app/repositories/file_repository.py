"""Data-access layer for the RepositoryFile aggregate.

Encapsulates all database interactions for the ``repository_files`` table.
No business logic lives here — only query construction, bulk-insert helpers,
and result hydration.
"""

import uuid
from collections import defaultdict
from typing import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.models.file import FileStatus, ProgrammingLanguage, RepositoryFile

logger = get_logger(__name__)


class FileRepository:
    """Data-access class for the RepositoryFile aggregate.

    All write operations use ``flush()`` instead of ``commit()`` so the
    caller (service layer) controls transaction boundaries.

    Args:
        session: An injected SQLAlchemy :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Read operations ───────────────────────────────────────────────────────

    async def get_by_id(self, file_id: uuid.UUID) -> RepositoryFile | None:
        """Fetch a single file record by its UUID primary key.

        Args:
            file_id: The UUID of the file record to retrieve.

        Returns:
            The :class:`~backend.app.models.file.RepositoryFile` instance,
            or ``None`` if not found.
        """
        result = await self._session.execute(
            select(RepositoryFile).where(RepositoryFile.id == file_id)
        )
        return result.scalar_one_or_none()

    async def get_by_repository_id(
        self,
        repository_id: uuid.UUID,
    ) -> list[RepositoryFile]:
        """Return all file records for a repository ordered by relative_path.

        Args:
            repository_id: The repository UUID to query.

        Returns:
            A list of :class:`~backend.app.models.file.RepositoryFile` instances.
        """
        result = await self._session.execute(
            select(RepositoryFile)
            .where(RepositoryFile.repository_id == repository_id)
            .order_by(RepositoryFile.relative_path)
        )
        return list(result.scalars().all())

    async def get_by_relative_path(
        self,
        repository_id: uuid.UUID,
        relative_path: str,
    ) -> RepositoryFile | None:
        """Fetch a file record by repository + relative path.

        Args:
            repository_id: The owning repository UUID.
            relative_path: POSIX-style path relative to the repository root.

        Returns:
            The matching :class:`~backend.app.models.file.RepositoryFile`,
            or ``None`` if not found.
        """
        result = await self._session.execute(
            select(RepositoryFile).where(
                RepositoryFile.repository_id == repository_id,
                RepositoryFile.relative_path == relative_path,
            )
        )
        return result.scalar_one_or_none()

    async def count_by_repository(self, repository_id: uuid.UUID) -> int:
        """Return the total number of file records for a repository.

        Args:
            repository_id: The repository UUID to count.

        Returns:
            Integer count of file records.
        """
        result = await self._session.execute(
            select(func.count(RepositoryFile.id)).where(
                RepositoryFile.repository_id == repository_id
            )
        )
        return result.scalar_one()

    async def count_by_status(
        self,
        repository_id: uuid.UUID,
        status: FileStatus,
    ) -> int:
        """Return the count of file records with a specific scan status.

        Args:
            repository_id: The repository UUID to query.
            status: The :class:`~backend.app.models.file.FileStatus` to filter by.

        Returns:
            Integer count.
        """
        result = await self._session.execute(
            select(func.count(RepositoryFile.id)).where(
                RepositoryFile.repository_id == repository_id,
                RepositoryFile.scan_status == status,
            )
        )
        return result.scalar_one()

    async def get_language_stats(
        self,
        repository_id: uuid.UUID,
    ) -> list[tuple[ProgrammingLanguage, int, int]]:
        """Return per-language (language, file_count, total_bytes) tuples.

        Only SCANNED files are included.

        Args:
            repository_id: The repository UUID to aggregate.

        Returns:
            A list of ``(language, file_count, total_bytes)`` tuples
            sorted by ``file_count`` descending.
        """
        result = await self._session.execute(
            select(
                RepositoryFile.language,
                func.count(RepositoryFile.id).label("file_count"),
                func.coalesce(func.sum(RepositoryFile.size_bytes), 0).label("total_bytes"),
            )
            .where(
                RepositoryFile.repository_id == repository_id,
                RepositoryFile.scan_status == FileStatus.SCANNED,
            )
            .group_by(RepositoryFile.language)
            .order_by(func.count(RepositoryFile.id).desc())
        )
        return [(row.language, int(row.file_count), int(row.total_bytes)) for row in result]

    # ── Write operations ──────────────────────────────────────────────────────

    async def bulk_upsert(
        self,
        records: Sequence[dict],
    ) -> int:
        """Bulk-upsert file records using PostgreSQL ``INSERT … ON CONFLICT DO UPDATE``.

        This is the primary write path for the scanner. Using upsert ensures
        that re-scanning a repository updates existing records rather than
        creating duplicates.

        The conflict target is the unique index on ``(repository_id, relative_path)``.

        Args:
            records: A sequence of dictionaries whose keys match
                     :class:`~backend.app.models.file.RepositoryFile` column names.

        Returns:
            The number of rows inserted or updated.
        """
        if not records:
            return 0

        stmt = pg_insert(RepositoryFile).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["repository_id", "relative_path"],
            set_={
                "absolute_path": stmt.excluded.absolute_path,
                "file_name": stmt.excluded.file_name,
                "extension": stmt.excluded.extension,
                "language": stmt.excluded.language,
                "mime_type": stmt.excluded.mime_type,
                "size_bytes": stmt.excluded.size_bytes,
                "sha256": stmt.excluded.sha256,
                "is_binary": stmt.excluded.is_binary,
                "is_hidden": stmt.excluded.is_hidden,
                "last_modified": stmt.excluded.last_modified,
                "scan_status": stmt.excluded.scan_status,
                "updated_at": func.now(),
            },
        )

        result = await self._session.execute(stmt)
        await self._session.flush()

        row_count: int = result.rowcount
        logger.debug(
            "Bulk upsert completed",
            row_count=row_count,
            record_count=len(records),
        )
        return row_count

    async def delete_by_repository(self, repository_id: uuid.UUID) -> int:
        """Delete all file records belonging to a repository.

        Called at the start of a re-scan to ensure a clean slate.

        Args:
            repository_id: The repository UUID whose files should be removed.

        Returns:
            The number of rows deleted.
        """
        result = await self._session.execute(
            delete(RepositoryFile).where(
                RepositoryFile.repository_id == repository_id
            )
        )
        await self._session.flush()
        row_count: int = result.rowcount

        logger.info(
            "File records deleted for repository",
            repository_id=str(repository_id),
            deleted_count=row_count,
        )
        return row_count
