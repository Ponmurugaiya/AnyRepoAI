"""Data-access layer for the Symbol Index.

Encapsulates all database interactions for the ``symbol_index_jobs`` and
``symbol_index_entries`` tables. Follows the same patterns as the existing
:class:`~backend.app.repositories.symbol_repository.SymbolRepository`:
    - All writes use ``flush()`` (not ``commit()``); transaction control
      stays in the service layer.
    - Bulk inserts use SQLAlchemy Core's ``insert()`` for performance.
    - Upserts use PostgreSQL ``INSERT … ON CONFLICT DO UPDATE``.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.symbol_index.models.index import IndexStatus, SymbolIndex, SymbolIndexEntry

logger = get_logger(__name__)

# Maximum rows per bulk-insert batch to control peak memory usage
_BULK_BATCH_SIZE = 500


class SymbolIndexRepository:
    """Data-access class for the Symbol Index tables.

    Args:
        session: An injected SQLAlchemy :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Index job management ───────────────────────────────────────────────────

    async def upsert_index_job(
        self,
        repository_id: uuid.UUID,
        *,
        status: IndexStatus,
        total_files: int = 0,
        indexed_files: int = 0,
        failed_files: int = 0,
        total_symbols: int = 0,
        duplicate_symbols: int = 0,
        error_message: str | None = None,
        index_duration_seconds: float = 0.0,
    ) -> SymbolIndex:
        """Create or update a :class:`SymbolIndex` job record for a repository.

        Uses ``INSERT … ON CONFLICT DO UPDATE`` on the unique
        ``repository_id`` constraint so re-indexing is idempotent.

        Args:
            repository_id: UUID of the owning repository.
            status: New lifecycle status.
            total_files: Total parseable files.
            indexed_files: Files successfully indexed.
            failed_files: Files that failed.
            total_symbols: Symbols written to the index.
            duplicate_symbols: Symbols skipped due to QN collision.
            error_message: Failure detail when status=FAILED.
            index_duration_seconds: Wall-clock duration of the run.

        Returns:
            The upserted :class:`SymbolIndex` record.
        """
        stmt = pg_insert(SymbolIndex).values(
            id=uuid.uuid4(),
            repository_id=repository_id,
            status=status,
            total_files=total_files,
            indexed_files=indexed_files,
            failed_files=failed_files,
            total_symbols=total_symbols,
            duplicate_symbols=duplicate_symbols,
            error_message=error_message,
            index_duration_seconds=index_duration_seconds,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["repository_id"],
            set_={
                "status": stmt.excluded.status,
                "total_files": stmt.excluded.total_files,
                "indexed_files": stmt.excluded.indexed_files,
                "failed_files": stmt.excluded.failed_files,
                "total_symbols": stmt.excluded.total_symbols,
                "duplicate_symbols": stmt.excluded.duplicate_symbols,
                "error_message": stmt.excluded.error_message,
                "index_duration_seconds": stmt.excluded.index_duration_seconds,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(stmt)
        await self._session.flush()

        result = await self._session.execute(
            select(SymbolIndex).where(SymbolIndex.repository_id == repository_id)
        )
        return result.scalar_one()

    async def get_index_job(self, repository_id: uuid.UUID) -> SymbolIndex | None:
        """Return the index job record for a repository.

        Args:
            repository_id: Repository UUID.

        Returns:
            :class:`SymbolIndex` or ``None`` if no job exists.
        """
        result = await self._session.execute(
            select(SymbolIndex).where(SymbolIndex.repository_id == repository_id)
        )
        return result.scalar_one_or_none()

    # ── Bulk write operations ──────────────────────────────────────────────────

    async def bulk_upsert_entries(
        self,
        entries: Sequence[dict[str, Any]],
    ) -> int:
        """Bulk-upsert symbol index entries.

        Uses PostgreSQL ``INSERT … ON CONFLICT DO UPDATE`` on the unique
        ``(repository_id, qualified_name)`` constraint. This means
        re-indexing a file updates existing entries rather than creating
        duplicates.

        Entries are processed in batches of :data:`_BULK_BATCH_SIZE` rows
        to bound peak memory usage.

        Args:
            entries: A sequence of column dicts for
                :class:`~backend.app.symbol_index.models.index.SymbolIndexEntry`.

        Returns:
            Total number of rows inserted or updated.
        """
        if not entries:
            return 0

        total_affected = 0

        for batch_start in range(0, len(entries), _BULK_BATCH_SIZE):
            batch = entries[batch_start : batch_start + _BULK_BATCH_SIZE]

            stmt = pg_insert(SymbolIndexEntry).values(list(batch))
            stmt = stmt.on_conflict_do_update(
                constraint="uq_symbol_index_repo_qualified_name",
                set_={
                    "file_id": stmt.excluded.file_id,
                    "language": stmt.excluded.language,
                    "symbol_type": stmt.excluded.symbol_type,
                    "name": stmt.excluded.name,
                    "display_name": stmt.excluded.display_name,
                    "parent_symbol_id": stmt.excluded.parent_symbol_id,
                    "module_name": stmt.excluded.module_name,
                    "namespace": stmt.excluded.namespace,
                    "signature": stmt.excluded.signature,
                    "return_type": stmt.excluded.return_type,
                    "visibility": stmt.excluded.visibility,
                    "is_static": stmt.excluded.is_static,
                    "is_async": stmt.excluded.is_async,
                    "is_exported": stmt.excluded.is_exported,
                    "is_deprecated": stmt.excluded.is_deprecated,
                    "documentation": stmt.excluded.documentation,
                    "start_line": stmt.excluded.start_line,
                    "end_line": stmt.excluded.end_line,
                    "start_column": stmt.excluded.start_column,
                    "end_column": stmt.excluded.end_column,
                    "updated_at": func.now(),
                },
            )

            result = await self._session.execute(stmt)
            total_affected += result.rowcount

        await self._session.flush()

        logger.debug(
            "Symbol index bulk upsert completed",
            total_affected=total_affected,
            total_input=len(entries),
        )
        return total_affected

    async def delete_entries_by_file(self, file_id: uuid.UUID) -> int:
        """Delete all index entries for a single file.

        Called before re-indexing a changed file to ensure a clean slate.

        Args:
            file_id: UUID of the source file whose entries to remove.

        Returns:
            Number of rows deleted.
        """
        result = await self._session.execute(
            delete(SymbolIndexEntry).where(SymbolIndexEntry.file_id == file_id)
        )
        await self._session.flush()
        count: int = result.rowcount
        logger.debug(
            "Symbol index entries deleted for file",
            file_id=str(file_id),
            deleted_count=count,
        )
        return count

    async def delete_entries_by_repository(self, repository_id: uuid.UUID) -> int:
        """Delete all index entries for a repository.

        Args:
            repository_id: Repository UUID.

        Returns:
            Number of rows deleted.
        """
        result = await self._session.execute(
            delete(SymbolIndexEntry).where(
                SymbolIndexEntry.repository_id == repository_id
            )
        )
        await self._session.flush()
        count: int = result.rowcount
        logger.info(
            "Symbol index entries deleted for repository",
            repository_id=str(repository_id),
            deleted_count=count,
        )
        return count

    # ── Query operations ───────────────────────────────────────────────────────

    async def get_entry_by_id(
        self, entry_id: uuid.UUID
    ) -> SymbolIndexEntry | None:
        """Fetch a single symbol index entry by UUID.

        Args:
            entry_id: The UUID primary key.

        Returns:
            :class:`SymbolIndexEntry` or ``None``.
        """
        result = await self._session.execute(
            select(SymbolIndexEntry).where(SymbolIndexEntry.id == entry_id)
        )
        return result.scalar_one_or_none()

    async def get_entry_by_qualified_name(
        self,
        repository_id: uuid.UUID,
        qualified_name: str,
    ) -> SymbolIndexEntry | None:
        """Fetch a symbol by its fully-qualified name within a repository.

        Args:
            repository_id: Repository UUID.
            qualified_name: Fully-qualified symbol name.

        Returns:
            :class:`SymbolIndexEntry` or ``None``.
        """
        result = await self._session.execute(
            select(SymbolIndexEntry).where(
                SymbolIndexEntry.repository_id == repository_id,
                SymbolIndexEntry.qualified_name == qualified_name,
            )
        )
        return result.scalar_one_or_none()

    async def list_entries(
        self,
        repository_id: uuid.UUID,
        *,
        language: str | None = None,
        symbol_type: str | None = None,
        file_id: uuid.UUID | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[SymbolIndexEntry]:
        """List symbol index entries for a repository with optional filters.

        Args:
            repository_id: Repository UUID.
            language: Optional language filter.
            symbol_type: Optional symbol-type filter.
            file_id: Optional file UUID filter (incremental use case).
            limit: Maximum rows to return.
            offset: Row offset for pagination.

        Returns:
            List of :class:`SymbolIndexEntry` instances.
        """
        stmt = (
            select(SymbolIndexEntry)
            .where(SymbolIndexEntry.repository_id == repository_id)
            .order_by(SymbolIndexEntry.qualified_name)
            .limit(limit)
            .offset(offset)
        )
        if language:
            stmt = stmt.where(SymbolIndexEntry.language == language)
        if symbol_type:
            stmt = stmt.where(SymbolIndexEntry.symbol_type == symbol_type)
        if file_id:
            stmt = stmt.where(SymbolIndexEntry.file_id == file_id)

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_entries(
        self,
        repository_id: uuid.UUID,
        *,
        language: str | None = None,
        symbol_type: str | None = None,
    ) -> int:
        """Count symbol index entries with optional filters.

        Args:
            repository_id: Repository UUID.
            language: Optional language filter.
            symbol_type: Optional symbol-type filter.

        Returns:
            Integer count.
        """
        stmt = select(func.count(SymbolIndexEntry.id)).where(
            SymbolIndexEntry.repository_id == repository_id
        )
        if language:
            stmt = stmt.where(SymbolIndexEntry.language == language)
        if symbol_type:
            stmt = stmt.where(SymbolIndexEntry.symbol_type == symbol_type)

        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def search_entries(
        self,
        repository_id: uuid.UUID,
        *,
        query: str,
        mode: str = "prefix",
        language: str | None = None,
        symbol_type: str | None = None,
        limit: int = 50,
    ) -> list[SymbolIndexEntry]:
        """Search symbol index entries by name or qualified name.

        Supported modes:

        ``prefix``
            Returns entries where ``name`` starts with ``query``
            (case-insensitive).  This is the fastest mode and the default.

        ``exact``
            Returns entries where ``name`` exactly equals ``query``
            (case-insensitive).

        ``qualified``
            Returns entries where ``qualified_name`` contains ``query``
            (case-insensitive substring match).

        Args:
            repository_id: Repository UUID.
            query: Search term.
            mode: One of ``"prefix"``, ``"exact"``, ``"qualified"``.
            language: Optional language filter.
            symbol_type: Optional symbol-type filter.
            limit: Maximum results to return.

        Returns:
            List of matching :class:`SymbolIndexEntry` instances ordered by
            ``qualified_name``.
        """
        stmt = (
            select(SymbolIndexEntry)
            .where(SymbolIndexEntry.repository_id == repository_id)
            .order_by(SymbolIndexEntry.qualified_name)
            .limit(limit)
        )

        query_lower = query.lower()

        if mode == "prefix":
            stmt = stmt.where(
                func.lower(SymbolIndexEntry.name).like(f"{query_lower}%")
            )
        elif mode == "exact":
            stmt = stmt.where(
                func.lower(SymbolIndexEntry.name) == query_lower
            )
        elif mode == "qualified":
            stmt = stmt.where(
                func.lower(SymbolIndexEntry.qualified_name).contains(query_lower)
            )
        else:
            # Fallback: prefix search
            stmt = stmt.where(
                func.lower(SymbolIndexEntry.name).like(f"{query_lower}%")
            )

        if language:
            stmt = stmt.where(SymbolIndexEntry.language == language)
        if symbol_type:
            stmt = stmt.where(SymbolIndexEntry.symbol_type == symbol_type)

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_children(
        self,
        parent_symbol_id: uuid.UUID,
    ) -> list[SymbolIndexEntry]:
        """Return all direct children of a symbol.

        Args:
            parent_symbol_id: UUID of the parent symbol entry.

        Returns:
            List of child :class:`SymbolIndexEntry` instances.
        """
        result = await self._session.execute(
            select(SymbolIndexEntry)
            .where(SymbolIndexEntry.parent_symbol_id == parent_symbol_id)
            .order_by(SymbolIndexEntry.name)
        )
        return list(result.scalars().all())

    async def get_qualified_name_map(
        self,
        repository_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> dict[str, uuid.UUID]:
        """Return a ``{qualified_name: id}`` map for entries in a file.

        Used to resolve ``parent_symbol_id`` when re-indexing a file whose
        parent symbols were already committed to the database in a prior batch.

        Args:
            repository_id: Repository UUID.
            file_id: File UUID.

        Returns:
            dict mapping qualified_name → UUID.
        """
        result = await self._session.execute(
            select(SymbolIndexEntry.qualified_name, SymbolIndexEntry.id).where(
                SymbolIndexEntry.repository_id == repository_id,
                SymbolIndexEntry.file_id == file_id,
            )
        )
        return {row.qualified_name: row.id for row in result}
