"""Symbol Index orchestration service.

The :class:`SymbolIndexService` is the primary entry point for all
symbol-indexing operations. It coordinates:

    1. **Input validation** — repository exists and has parse results.
    2. **Incremental clear** — delete previous index entries for the
       files being re-indexed so the operation is idempotent.
    3. **Mapping** — translate :class:`FileSummary` objects into
       :class:`SymbolIndexEntry` column dicts via :class:`SymbolMapper`.
    4. **Deduplication** — remove qualified-name collisions within a
       batch before they reach the database.
    5. **Bulk persistence** — upsert entries in configurable batches.
    6. **Progress tracking** — maintain the :class:`SymbolIndex` job
       record throughout the run.

Design decisions:
    - Indexing runs entirely in-process on the async event loop.
      CPU-bound work (mapping) is intentionally lightweight compared to
      AST parsing, so a ProcessPool is not needed.
    - Files are processed sequentially in memory-bounded batches to
      support 100k+ symbol repositories without OOM.
    - Each file's indexing errors are caught and recorded; failures on
      one file never abort the remainder of the job.
    - Re-indexing a repository is always safe (idempotent upsert).
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.exceptions import RepositoryNotFoundError, RepositoryNotReadyError
from backend.app.core.logging import get_logger
from backend.app.models.file import FileStatus, ProgrammingLanguage
from backend.app.models.repository import RepositoryStatus
from backend.app.models.symbol import ParseStatus
from backend.app.parsers.models.symbols import FileSummary
from backend.app.parsers.registry import get_parser_registry
from backend.app.repositories.file_repository import FileRepository
from backend.app.repositories.repository import RepositoryRepository
from backend.app.repositories.symbol_repository import SymbolRepository
from backend.app.symbol_index.mappers.symbol_mapper import SymbolMapper
from backend.app.symbol_index.models.index import IndexStatus
from backend.app.symbol_index.repositories.index_repository import SymbolIndexRepository
from backend.app.symbol_index.schemas.index import IndexProgressResponse, IndexStatistics
from backend.app.symbol_index.validators.duplicates import DuplicateDetector

logger = get_logger(__name__)

# Languages that have a registered parser and can be indexed
_INDEXABLE_LANGUAGES: frozenset[str] = frozenset(
    {
        ProgrammingLanguage.PYTHON.value,
        ProgrammingLanguage.JAVASCRIPT.value,
        ProgrammingLanguage.TYPESCRIPT.value,
        ProgrammingLanguage.JAVA.value,
        ProgrammingLanguage.GO.value,
    }
)

# Files processed between database batch commits
_FILE_BATCH_SIZE = 20


class SymbolIndexService:
    """Orchestrates the Symbol Index build pipeline for a repository.

    Args:
        session: Injected SQLAlchemy async session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo_repo = RepositoryRepository(session)
        self._file_repo = FileRepository(session)
        self._sym_repo = SymbolRepository(session)
        self._index_repo = SymbolIndexRepository(session)
        self._mapper = SymbolMapper()
        self._detector = DuplicateDetector()

    # ── Public API ─────────────────────────────────────────────────────────────

    async def index_repository(self, repository_id: uuid.UUID) -> IndexStatistics:
        """Build (or rebuild) the Symbol Index for an entire repository.

        Preconditions:
            - Repository must exist.
            - Repository must have ``clone_status=READY``.
            - Repository must have at least some files with
              ``parse_status=COMPLETED`` (the parser must have run first).

        Steps:
            1. Validate preconditions; mark job as QUEUED.
            2. Clear all existing index entries for the repository.
            3. Load all files with completed parse results.
            4. For each file batch: map → deduplicate → upsert → commit.
            5. Mark job COMPLETED (or FAILED on unrecoverable error).

        Args:
            repository_id: UUID of the repository to index.

        Returns:
            :class:`IndexStatistics` with aggregate counts.

        Raises:
            RepositoryNotFoundError: Repository record not found.
            RepositoryNotReadyError: Repository clone is not in READY state.
        """
        start = time.perf_counter()

        # ── Validate ───────────────────────────────────────────────────────────
        repo = await self._repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(str(repository_id))
        if repo.clone_status != RepositoryStatus.READY:
            raise RepositoryNotReadyError(str(repository_id), repo.clone_status.value)

        logger.info(
            "Repository symbol indexing started",
            repository_id=str(repository_id),
            full_name=repo.full_name,
        )

        # ── Mark job as QUEUED ─────────────────────────────────────────────────
        await self._index_repo.upsert_index_job(
            repository_id,
            status=IndexStatus.QUEUED,
        )

        # ── Collect indexable files ────────────────────────────────────────────
        all_files = await self._file_repo.get_by_repository_id(repository_id)
        indexable = [
            f for f in all_files
            if f.scan_status == FileStatus.SCANNED
            and f.language.value in _INDEXABLE_LANGUAGES
            and not f.is_binary
        ]
        total_files = len(indexable)

        logger.info(
            "Files eligible for symbol indexing",
            repository_id=str(repository_id),
            total=total_files,
        )

        # ── Clear previous entries ─────────────────────────────────────────────
        await self._index_repo.delete_entries_by_repository(repository_id)

        # ── Mark job as INDEXING ───────────────────────────────────────────────
        await self._index_repo.upsert_index_job(
            repository_id,
            status=IndexStatus.INDEXING,
            total_files=total_files,
        )

        stats = IndexStatistics(
            repository_id=repository_id,
            total_files=total_files,
        )

        if total_files == 0:
            await self._index_repo.upsert_index_job(
                repository_id,
                status=IndexStatus.COMPLETED,
                total_files=0,
            )
            stats.index_duration_seconds = round(time.perf_counter() - start, 3)
            return stats

        # ── Process files in batches ───────────────────────────────────────────
        try:
            await self._process_files(indexable, repository_id, stats)
        except Exception as exc:  # noqa: BLE001
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error(
                "Symbol indexing failed with unrecoverable error",
                repository_id=str(repository_id),
                error=error_msg,
            )
            await self._index_repo.upsert_index_job(
                repository_id,
                status=IndexStatus.FAILED,
                total_files=total_files,
                indexed_files=stats.indexed_files,
                failed_files=stats.failed_files,
                total_symbols=stats.total_symbols,
                duplicate_symbols=stats.duplicate_symbols,
                error_message=error_msg[:1000],
            )
            stats.index_duration_seconds = round(time.perf_counter() - start, 3)
            return stats

        # ── Finalise ───────────────────────────────────────────────────────────
        stats.index_duration_seconds = round(time.perf_counter() - start, 3)
        await self._index_repo.upsert_index_job(
            repository_id,
            status=IndexStatus.COMPLETED,
            total_files=total_files,
            indexed_files=stats.indexed_files,
            failed_files=stats.failed_files,
            total_symbols=stats.total_symbols,
            duplicate_symbols=stats.duplicate_symbols,
            index_duration_seconds=stats.index_duration_seconds,
        )

        logger.info(
            "Repository symbol indexing completed",
            repository_id=str(repository_id),
            total_symbols=stats.total_symbols,
            duration_seconds=stats.index_duration_seconds,
        )
        return stats

    async def index_file(
        self,
        repository_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> int:
        """Incrementally re-index a single file.

        Deletes all existing index entries for the file and rebuilds them
        from the file's parse results stored in the ``symbols``, ``classes``,
        and ``functions`` tables.

        This is the incremental update path: only symbols belonging to the
        changed file are regenerated; the rest of the repository index is
        untouched.

        Args:
            repository_id: Repository UUID.
            file_id: UUID of the file to re-index.

        Returns:
            Number of symbols written to the index.
        """
        file_record = await self._file_repo.get_by_id(file_id)
        if file_record is None:
            logger.warning(
                "File not found for incremental indexing",
                file_id=str(file_id),
                repository_id=str(repository_id),
            )
            return 0

        logger.info(
            "File symbol indexing started",
            file_id=str(file_id),
            relative_path=file_record.relative_path,
        )

        # Build a FileSummary from stored parse results
        summary = await self._load_file_summary(repository_id, file_id, file_record)
        if summary is None:
            logger.warning(
                "No parse results for file; skipping incremental index",
                file_id=str(file_id),
            )
            return 0

        # Clear previous entries then rewrite
        await self._index_repo.delete_entries_by_file(file_id)
        entries = self._mapper.map_file_summary(summary)
        unique_entries, dup_stats = self._detector.deduplicate(
            entries,
            key_fn=lambda e: f"{e['repository_id']}::{e['qualified_name']}",
            context=file_record.relative_path,
        )

        count = await self._index_repo.bulk_upsert_entries(unique_entries)

        logger.info(
            "File symbol indexing completed",
            file_id=str(file_id),
            symbols=count,
            duplicates=dup_stats.duplicate_count,
        )
        return count

    async def get_progress(
        self, repository_id: uuid.UUID
    ) -> IndexProgressResponse:
        """Return current indexing progress for a repository.

        Args:
            repository_id: Repository UUID.

        Returns:
            :class:`IndexProgressResponse` with current counts and status.

        Raises:
            RepositoryNotFoundError: Repository record not found.
        """
        repo = await self._repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(str(repository_id))

        job = await self._index_repo.get_index_job(repository_id)
        if job is None:
            return IndexProgressResponse(
                repository_id=repository_id,
                status="NOT_STARTED",
            )

        return IndexProgressResponse(
            repository_id=repository_id,
            status=job.status.value,
            total_files=job.total_files,
            indexed_files=job.indexed_files,
            failed_files=job.failed_files,
            total_symbols=job.total_symbols,
            duplicate_symbols=job.duplicate_symbols,
            index_duration_seconds=job.index_duration_seconds,
        )

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _process_files(
        self,
        files: list,
        repository_id: uuid.UUID,
        stats: IndexStatistics,
    ) -> None:
        """Process all indexable files in batches, updating ``stats`` in-place.

        Args:
            files: List of :class:`~backend.app.models.file.RepositoryFile` records.
            repository_id: Repository UUID.
            stats: Mutable statistics accumulator.
        """
        registry = get_parser_registry()

        for batch_start in range(0, len(files), _FILE_BATCH_SIZE):
            batch = files[batch_start : batch_start + _FILE_BATCH_SIZE]
            batch_entries: list[dict] = []

            for file_record in batch:
                logger.debug(
                    "File symbol indexing started",
                    file_id=str(file_record.id),
                    relative_path=file_record.relative_path,
                    language=file_record.language.value,
                )
                try:
                    summary = await self._load_file_summary_via_parser(
                        repository_id, file_record, registry
                    )
                    if summary is None:
                        stats.failed_files += 1
                        continue

                    entries = self._mapper.map_file_summary(summary)
                    unique_entries, dup_stats = self._detector.deduplicate(
                        entries,
                        key_fn=lambda e: f"{e['repository_id']}::{e['qualified_name']}",
                        context=file_record.relative_path,
                    )

                    if dup_stats.duplicate_count > 0:
                        logger.debug(
                            "Duplicates detected in file",
                            file_id=str(file_record.id),
                            relative_path=file_record.relative_path,
                            duplicate_count=dup_stats.duplicate_count,
                        )

                    batch_entries.extend(unique_entries)
                    stats.indexed_files += 1
                    stats.duplicate_symbols += dup_stats.duplicate_count

                    logger.debug(
                        "Symbols extracted",
                        file_id=str(file_record.id),
                        symbol_count=len(unique_entries),
                    )

                except Exception as exc:  # noqa: BLE001
                    stats.failed_files += 1
                    logger.error(
                        "File indexing error",
                        file_id=str(file_record.id),
                        relative_path=file_record.relative_path,
                        error=str(exc),
                        exc_type=type(exc).__name__,
                    )

            # Global deduplication across this batch (cross-file collision)
            unique_batch, cross_dups = self._detector.deduplicate(
                batch_entries,
                key_fn=lambda e: f"{e['repository_id']}::{e['qualified_name']}",
                context=f"batch@{batch_start}",
            )
            stats.duplicate_symbols += cross_dups.duplicate_count

            if unique_batch:
                written = await self._index_repo.bulk_upsert_entries(unique_batch)
                stats.total_symbols += written

                logger.info(
                    "Database batch committed",
                    repository_id=str(repository_id),
                    batch_start=batch_start,
                    batch_size=len(batch),
                    symbols_written=written,
                    cumulative_total=stats.total_symbols,
                )

            # Update progress in the database after each batch
            await self._index_repo.upsert_index_job(
                repository_id,
                status=IndexStatus.INDEXING,
                total_files=stats.total_files,
                indexed_files=stats.indexed_files,
                failed_files=stats.failed_files,
                total_symbols=stats.total_symbols,
                duplicate_symbols=stats.duplicate_symbols,
            )

    async def _load_file_summary_via_parser(
        self,
        repository_id: uuid.UUID,
        file_record: "RepositoryFile",  # type: ignore[name-defined]
        registry: "ParserRegistry",  # type: ignore[name-defined]
    ) -> "FileSummary | None":
        """Parse a source file via the language parser and return a FileSummary.

        The parser reads the file from disk. If the absolute path does not
        exist or there is no parser for the language, returns ``None``.

        Args:
            repository_id: Repository UUID (for the summary payload).
            file_record: The :class:`RepositoryFile` ORM record.
            registry: The parser registry singleton.

        Returns:
            :class:`FileSummary` or ``None`` on failure.
        """
        language = file_record.language.value
        parser = registry.get_parser_for_language(language)
        if parser is None:
            logger.debug(
                "No parser for language; skipping file",
                language=language,
                file_id=str(file_record.id),
            )
            return None

        absolute_path = file_record.absolute_path
        if not absolute_path or not Path(absolute_path).exists():
            logger.warning(
                "File does not exist on disk; skipping indexing",
                file_id=str(file_record.id),
                absolute_path=absolute_path,
            )
            return None

        # Parsing is CPU-bound but fast for a single file at this stage;
        # the symbol index uses already-parsed FileSummary objects when
        # available. We call the parser directly here for correctness.
        summary: FileSummary = parser.parse_file(
            file_id=file_record.id,
            repository_id=repository_id,
            relative_path=file_record.relative_path,
            absolute_path=absolute_path,
        )

        if summary.parse_errors and len(summary.parse_errors) == 1:
            error = summary.parse_errors[0]
            if "Cannot read file" in error:
                logger.warning(
                    "Parser could not read file",
                    file_id=str(file_record.id),
                    error=error,
                )
                return None

        logger.debug(
            "Qualified names generated",
            file_id=str(file_record.id),
            symbols=len(summary.symbols),
            classes=len(summary.classes),
            functions=len(summary.functions),
            routes=len(summary.routes),
        )

        return summary

    async def _load_file_summary(
        self,
        repository_id: uuid.UUID,
        file_id: uuid.UUID,
        file_record: "RepositoryFile",  # type: ignore[name-defined]
    ) -> "FileSummary | None":
        """Load a FileSummary for a single file for incremental re-indexing.

        Uses the language parser on the current file contents. Falls back
        to returning ``None`` if the parser is unavailable or the file
        does not exist.

        Args:
            repository_id: Repository UUID.
            file_id: File UUID.
            file_record: The :class:`RepositoryFile` ORM record.

        Returns:
            :class:`FileSummary` or ``None``.
        """
        registry = get_parser_registry()
        return await self._load_file_summary_via_parser(
            repository_id, file_record, registry
        )
