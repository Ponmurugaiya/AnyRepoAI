"""Code Intelligence Engine — parser service.

Orchestrates multi-language AST parsing of a scanned repository.
Reads ``repository_files`` records whose language has a registered
parser, dispatches each file to the appropriate language parser, and
persists the extracted symbol database.

Design decisions
----------------
- Parsing is incremental: files are processed in configurable batches,
  bounding memory usage regardless of repository size.
- Parallelism: CPU-bound parse work runs in a ``ProcessPoolExecutor``
  via ``asyncio.run_in_executor`` so the event loop never blocks.
- Fault isolation: a parse failure on one file never aborts the job;
  the file is marked FAILED and parsing continues.
- Idempotency: re-parsing a repository deletes previous results first.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
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
from backend.app.schemas.parser import (
    ParseInitiatedResponse,
    ParseProgressResponse,
    ParseStatistics,
)

logger = get_logger(__name__)

# Languages for which a parser exists — keeps in sync with registry automatically
_PARSEABLE_LANGUAGES: frozenset[str] = frozenset(
    {
        ProgrammingLanguage.PYTHON.value,
        ProgrammingLanguage.JAVASCRIPT.value,
        ProgrammingLanguage.TYPESCRIPT.value,
        ProgrammingLanguage.JAVA.value,
        ProgrammingLanguage.GO.value,
    }
)


def _parse_file_worker(
    file_id_str: str,
    repository_id_str: str,
    relative_path: str,
    absolute_path: str,
    language: str,
) -> dict:
    """Worker function executed in a subprocess for CPU-bound parsing.

    This function is the only entry point called inside the process pool.
    It imports the registry on first call (which loads tree-sitter grammars),
    runs the parse, and returns a serialisable result dict.

    Args:
        file_id_str: File UUID as string.
        repository_id_str: Repository UUID as string.
        relative_path: POSIX relative path.
        absolute_path: Absolute filesystem path.
        language: Language name string.

    Returns:
        dict with keys:
            ``file_id``, ``success``, ``error``, ``summary_json``
            (serialised :class:`FileSummary` JSON).
    """
    import json as _json

    try:
        registry = get_parser_registry()
        parser = registry.get_parser_for_language(language)
        if parser is None:
            return {
                "file_id": file_id_str,
                "success": False,
                "error": f"No parser for language: {language}",
                "summary_json": None,
            }

        summary: FileSummary = parser.parse_file(
            file_id=uuid.UUID(file_id_str),
            repository_id=uuid.UUID(repository_id_str),
            relative_path=relative_path,
            absolute_path=absolute_path,
        )
        return {
            "file_id": file_id_str,
            "success": not bool(
                summary.parse_errors and len(summary.parse_errors) == 1
                and "Cannot read file" in summary.parse_errors[0]
            ),
            "error": "; ".join(summary.parse_errors) if summary.parse_errors else None,
            "summary_json": summary.model_dump_json(),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "file_id": file_id_str,
            "success": False,
            "error": f"{type(exc).__name__}: {exc}",
            "summary_json": None,
        }


class RepositoryParserService:
    """Orchestrates full-repository AST parsing.

    Args:
        session: Injected SQLAlchemy async session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo_repo = RepositoryRepository(session)
        self._file_repo = FileRepository(session)
        self._sym_repo = SymbolRepository(session)
        self._settings = get_settings()

    # ── Public API ─────────────────────────────────────────────────────────────

    async def parse_repository(self, repository_id: uuid.UUID) -> ParseStatistics:
        """Parse all parseable source files in a repository.

        Validation:
            - Repository must exist and have ``clone_status=READY``.

        Steps:
            1. Delete previous intelligence records.
            2. Query all ``SCANNED`` files with a supported language.
            3. Enqueue parse jobs (status=QUEUED).
            4. Process files in parallel batches.
            5. Persist extracted symbols per file.
            6. Return aggregate statistics.

        Args:
            repository_id: UUID of the repository to parse.

        Returns:
            :class:`~backend.app.schemas.parser.ParseStatistics` aggregate.

        Raises:
            RepositoryNotFoundError: Repository record not found.
            RepositoryNotReadyError: Repository is not in READY state.
        """
        start = time.perf_counter()

        repo = await self._repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(str(repository_id))
        if repo.clone_status != RepositoryStatus.READY:
            raise RepositoryNotReadyError(str(repository_id), repo.clone_status.value)

        logger.info(
            "Repository parse started",
            repository_id=str(repository_id),
            full_name=repo.full_name,
        )

        # Wipe previous results for idempotency
        await self._sym_repo.delete_by_repository(repository_id)

        # Load parseable files
        all_files = await self._file_repo.get_by_repository_id(repository_id)
        parseable = [
            f for f in all_files
            if f.scan_status == FileStatus.SCANNED
            and f.language.value in _PARSEABLE_LANGUAGES
            and not f.is_binary
            and f.absolute_path
            and Path(f.absolute_path).exists()
        ]

        total = len(parseable)
        logger.info(
            "Files eligible for parsing",
            repository_id=str(repository_id),
            total=total,
        )

        if total == 0:
            return ParseStatistics(
                repository_id=repository_id,
                total_files=0,
                completed_files=0,
                failed_files=0,
                total_symbols=0,
                total_imports=0,
                total_calls=0,
                total_functions=0,
                total_classes=0,
                total_routes=0,
                parse_duration_seconds=0.0,
            )

        # Mark all as QUEUED upfront for progress visibility
        for f in parseable:
            await self._sym_repo.upsert_parse_job(
                file_id=f.id,
                repository_id=repository_id,
                status=ParseStatus.QUEUED,
                language=f.language.value,
            )

        # Process in parallel batches
        stats = ParseStatistics(repository_id=repository_id, total_files=total)
        batch_size = self._settings.parser.parse_batch_size
        max_workers = self._settings.parser.parse_max_workers
        loop = asyncio.get_event_loop()

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            for batch_start in range(0, total, batch_size):
                batch = parseable[batch_start:batch_start + batch_size]
                futures = [
                    loop.run_in_executor(
                        executor,
                        _parse_file_worker,
                        str(f.id),
                        str(repository_id),
                        f.relative_path,
                        f.absolute_path,
                        f.language.value,
                    )
                    for f in batch
                ]
                results = await asyncio.gather(*futures, return_exceptions=True)
                await self._process_batch_results(results, repository_id, stats)

                logger.info(
                    "Parse batch completed",
                    repository_id=str(repository_id),
                    batch_start=batch_start,
                    batch_size=len(batch),
                    completed=stats.completed_files,
                    failed=stats.failed_files,
                )

        stats.parse_duration_seconds = round(time.perf_counter() - start, 3)
        logger.info(
            "Repository parse completed",
            repository_id=str(repository_id),
            **stats.model_dump(exclude={"repository_id"}),
        )
        return stats

    async def _process_batch_results(
        self,
        results: list,
        repository_id: uuid.UUID,
        stats: "ParseStatistics",
    ) -> None:
        """Persist parse results from one batch into the database.

        Args:
            results: List of result dicts or exceptions from the process pool.
            repository_id: Repository UUID for job updates.
            stats: Mutable statistics accumulator (updated in-place).
        """
        for result in results:
            if isinstance(result, Exception):
                stats.failed_files += 1
                logger.error(
                    "Parse worker raised exception",
                    repository_id=str(repository_id),
                    error=str(result),
                )
                continue

            file_id_str = result.get("file_id", "unknown")

            if not result.get("success") or not result.get("summary_json"):
                stats.failed_files += 1
                error_msg = result.get("error", "Unknown error")
                logger.warning(
                    "File parse failed",
                    file_id=file_id_str,
                    error=error_msg,
                )
                try:
                    await self._sym_repo.upsert_parse_job(
                        file_id=uuid.UUID(file_id_str),
                        repository_id=repository_id,
                        status=ParseStatus.FAILED,
                        error_message=error_msg[:1000],
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error("Failed to record parse failure", error=str(exc))
                continue

            try:
                summary = FileSummary.model_validate_json(result["summary_json"])
                await self._sym_repo.delete_by_file(summary.file_id)
                await self._sym_repo.bulk_insert_summary(summary)
                await self._sym_repo.upsert_parse_job(
                    file_id=summary.file_id,
                    repository_id=repository_id,
                    status=ParseStatus.COMPLETED,
                    language=summary.language,
                    parse_duration_ms=summary.parse_duration_ms,
                    symbol_count=len(summary.symbols),
                    import_count=len(summary.imports),
                    call_count=len(summary.calls),
                    function_count=len(summary.functions),
                    class_count=len(summary.classes),
                    route_count=len(summary.routes),
                )
                stats.completed_files += 1
                stats.total_symbols += len(summary.symbols)
                stats.total_imports += len(summary.imports)
                stats.total_calls += len(summary.calls)
                stats.total_functions += len(summary.functions)
                stats.total_classes += len(summary.classes)
                stats.total_routes += len(summary.routes)

                logger.debug(
                    "File parsed and persisted",
                    file_id=file_id_str,
                    language=summary.language,
                    symbols=len(summary.symbols),
                    routes=len(summary.routes),
                    parse_ms=summary.parse_duration_ms,
                )
            except Exception as exc:  # noqa: BLE001
                stats.failed_files += 1
                logger.error(
                    "Failed to persist parse results",
                    file_id=file_id_str,
                    error=str(exc),
                    exc_type=type(exc).__name__,
                )
                try:
                    await self._sym_repo.upsert_parse_job(
                        file_id=uuid.UUID(file_id_str),
                        repository_id=repository_id,
                        status=ParseStatus.FAILED,
                        error_message=str(exc)[:1000],
                    )
                except Exception:  # noqa: BLE001
                    pass

    async def get_parse_progress(
        self, repository_id: uuid.UUID
    ) -> ParseProgressResponse:
        """Return current parse progress for a repository.

        Args:
            repository_id: Repository UUID.

        Returns:
            :class:`~backend.app.schemas.parser.ParseProgressResponse`.

        Raises:
            RepositoryNotFoundError: Repository record not found.
        """
        repo = await self._repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(str(repository_id))

        progress = await self._sym_repo.get_parse_progress(repository_id)
        total = sum(progress.values())
        completed = progress.get("COMPLETED", 0)
        failed = progress.get("FAILED", 0)
        queued = progress.get("QUEUED", 0)
        parsing = progress.get("PARSING", 0)

        if total == 0:
            overall = "NOT_STARTED"
        elif completed + failed == total:
            overall = "COMPLETED" if failed == 0 else "COMPLETED_WITH_ERRORS"
        elif parsing > 0 or queued < total:
            overall = "PARSING"
        else:
            overall = "QUEUED"

        return ParseProgressResponse(
            repository_id=repository_id,
            status=overall,
            total_files=total,
            queued=queued,
            parsing=parsing,
            completed=completed,
            failed=failed,
        )
