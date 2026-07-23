"""Data-access layer for all Code Intelligence Engine tables.

Encapsulates all database interactions for symbols, imports, calls,
routes, classes, functions, and parse job tracking.

All write operations use ``flush()`` to keep transaction control in the
service layer, consistent with the existing repository pattern.
"""

from __future__ import annotations

import json
import uuid
from typing import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.models.symbol import (
    CallRecord,
    ClassRecord,
    FileParseJob,
    FunctionRecord,
    ImportRecord,
    ParseStatus,
    RouteRecord,
    Symbol,
    SymbolType,
)
from backend.app.parsers.models.symbols import FileSummary

logger = get_logger(__name__)


class SymbolRepository:
    """Data-access class for the Code Intelligence Engine.

    Owns all read/write operations for the intelligence tables.
    Uses bulk-insert patterns identical to ``FileRepository`` for
    scalability to 100k+ file repositories.

    Args:
        session: An injected SQLAlchemy :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Parse job management ──────────────────────────────────────────────────

    async def upsert_parse_job(
        self,
        file_id: uuid.UUID,
        repository_id: uuid.UUID,
        status: ParseStatus,
        language: str | None = None,
        error_message: str | None = None,
        parse_duration_ms: float = 0.0,
        symbol_count: int = 0,
        import_count: int = 0,
        call_count: int = 0,
        function_count: int = 0,
        class_count: int = 0,
        route_count: int = 0,
    ) -> FileParseJob:
        """Create or update a parse job record for a file.

        Uses ``INSERT … ON CONFLICT DO UPDATE`` on the unique ``file_id``
        constraint so re-parsing overwrites the previous result atomically.

        Args:
            file_id: UUID of the ``repository_files`` record.
            repository_id: UUID of the owning repository.
            status: New :class:`~backend.app.models.symbol.ParseStatus`.
            language: Parser language name.
            error_message: Failure detail when status=FAILED.
            parse_duration_ms: Wall-clock parse time.
            symbol_count: Number of symbols extracted.
            import_count: Number of imports extracted.
            call_count: Number of calls extracted.
            function_count: Number of functions extracted.
            class_count: Number of classes extracted.
            route_count: Number of routes extracted.

        Returns:
            The upserted :class:`~backend.app.models.symbol.FileParseJob`.
        """
        stmt = pg_insert(FileParseJob).values(
            id=uuid.uuid4(),
            file_id=file_id,
            repository_id=repository_id,
            parse_status=status,
            language=language,
            error_message=error_message,
            parse_duration_ms=parse_duration_ms,
            symbol_count=symbol_count,
            import_count=import_count,
            call_count=call_count,
            function_count=function_count,
            class_count=class_count,
            route_count=route_count,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_file_parse_jobs_file_id",
            set_={
                "parse_status": stmt.excluded.parse_status,
                "language": stmt.excluded.language,
                "error_message": stmt.excluded.error_message,
                "parse_duration_ms": stmt.excluded.parse_duration_ms,
                "symbol_count": stmt.excluded.symbol_count,
                "import_count": stmt.excluded.import_count,
                "call_count": stmt.excluded.call_count,
                "function_count": stmt.excluded.function_count,
                "class_count": stmt.excluded.class_count,
                "route_count": stmt.excluded.route_count,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(stmt)
        await self._session.flush()

        result = await self._session.execute(
            select(FileParseJob).where(FileParseJob.file_id == file_id)
        )
        job = result.scalar_one()
        return job

    async def get_parse_job(self, file_id: uuid.UUID) -> FileParseJob | None:
        """Return the parse job for a file, or None.

        Args:
            file_id: Source file UUID.

        Returns:
            :class:`~backend.app.models.symbol.FileParseJob` or ``None``.
        """
        result = await self._session.execute(
            select(FileParseJob).where(FileParseJob.file_id == file_id)
        )
        return result.scalar_one_or_none()

    async def count_parse_jobs_by_status(
        self, repository_id: uuid.UUID, status: ParseStatus
    ) -> int:
        """Count parse jobs for a repository by status.

        Args:
            repository_id: Repository UUID.
            status: Status to filter by.

        Returns:
            Integer count.
        """
        result = await self._session.execute(
            select(func.count(FileParseJob.id)).where(
                FileParseJob.repository_id == repository_id,
                FileParseJob.parse_status == status,
            )
        )
        return result.scalar_one()

    async def get_parse_progress(self, repository_id: uuid.UUID) -> dict[str, int]:
        """Return a status-keyed count dict for a repository's parse jobs.

        Args:
            repository_id: Repository UUID.

        Returns:
            dict mapping status name → count, e.g.
            ``{"QUEUED": 5, "PARSING": 2, "COMPLETED": 93, "FAILED": 0}``.
        """
        result = await self._session.execute(
            select(FileParseJob.parse_status, func.count(FileParseJob.id))
            .where(FileParseJob.repository_id == repository_id)
            .group_by(FileParseJob.parse_status)
        )
        counts: dict[str, int] = {s.value: 0 for s in ParseStatus}
        for status, count in result:
            counts[status.value] = count
        return counts

    # ── Symbol persistence ─────────────────────────────────────────────────────

    async def delete_by_file(self, file_id: uuid.UUID) -> None:
        """Delete all intelligence records for a single file.

        Called before re-parsing a file to ensure a clean slate.

        Args:
            file_id: UUID of the file whose records should be wiped.
        """
        for model in (Symbol, ImportRecord, CallRecord, RouteRecord, ClassRecord, FunctionRecord):
            await self._session.execute(
                delete(model).where(model.file_id == file_id)
            )
        await self._session.flush()

    async def delete_by_repository(self, repository_id: uuid.UUID) -> None:
        """Delete all intelligence records for an entire repository.

        Args:
            repository_id: Repository UUID.
        """
        for model in (
            Symbol, ImportRecord, CallRecord, RouteRecord,
            ClassRecord, FunctionRecord, FileParseJob,
        ):
            await self._session.execute(
                delete(model).where(model.repository_id == repository_id)
            )
        await self._session.flush()
        logger.info("Intelligence records deleted", repository_id=str(repository_id))

    async def bulk_insert_summary(self, summary: FileSummary) -> None:
        """Persist all extracted data from a :class:`FileSummary`.

        Inserts symbols, imports, calls, classes, functions, and routes
        in individual bulk batches. Each table is inserted separately so
        partial failures are scoped to a single table type.

        Args:
            summary: The :class:`~backend.app.parsers.models.symbols.FileSummary`
                output from a language parser.
        """
        fid = summary.file_id
        rid = summary.repository_id

        # ── Symbols ───────────────────────────────────────────────────────────
        if summary.symbols:
            await self._session.execute(
                Symbol.__table__.insert(),
                [
                    {
                        "id": s.id,
                        "repository_id": rid,
                        "file_id": fid,
                        "symbol_name": s.symbol_name,
                        "qualified_name": s.qualified_name,
                        "symbol_type": s.symbol_type.value,
                        "visibility": s.visibility.value,
                        "start_line": s.start_line,
                        "end_line": s.end_line,
                        "language": s.language,
                        "parent_symbol": s.parent_symbol,
                        "documentation": s.documentation,
                        "signature": s.signature,
                    }
                    for s in summary.symbols
                ],
            )

        # ── Imports ───────────────────────────────────────────────────────────
        if summary.imports:
            await self._session.execute(
                ImportRecord.__table__.insert(),
                [
                    {
                        "id": imp.id,
                        "repository_id": rid,
                        "file_id": fid,
                        "module_path": imp.module_path,
                        "imported_names": json.dumps(imp.imported_names),
                        "alias": imp.alias,
                        "is_relative": imp.is_relative,
                        "start_line": imp.start_line,
                        "language": imp.language,
                    }
                    for imp in summary.imports
                ],
            )

        # ── Calls ─────────────────────────────────────────────────────────────
        if summary.calls:
            await self._session.execute(
                CallRecord.__table__.insert(),
                [
                    {
                        "id": c.id,
                        "repository_id": rid,
                        "file_id": fid,
                        "caller_name": c.caller_name,
                        "callee_name": c.callee_name,
                        "callee_object": c.callee_object,
                        "start_line": c.start_line,
                        "language": c.language,
                    }
                    for c in summary.calls
                ],
            )

        # ── Classes ───────────────────────────────────────────────────────────
        if summary.classes:
            await self._session.execute(
                ClassRecord.__table__.insert(),
                [
                    {
                        "id": cls.id,
                        "repository_id": rid,
                        "file_id": fid,
                        "class_name": cls.class_name,
                        "qualified_name": cls.qualified_name,
                        "base_classes": json.dumps(cls.base_classes),
                        "interfaces": json.dumps(cls.interfaces),
                        "visibility": cls.visibility.value,
                        "is_abstract": cls.is_abstract,
                        "start_line": cls.start_line,
                        "end_line": cls.end_line,
                        "language": cls.language,
                        "documentation": cls.documentation,
                        "decorators": json.dumps(cls.decorators),
                    }
                    for cls in summary.classes
                ],
            )

        # ── Functions ─────────────────────────────────────────────────────────
        if summary.functions:
            await self._session.execute(
                FunctionRecord.__table__.insert(),
                [
                    {
                        "id": fn.id,
                        "repository_id": rid,
                        "file_id": fid,
                        "function_name": fn.function_name,
                        "qualified_name": fn.qualified_name,
                        "is_method": fn.is_method,
                        "is_constructor": fn.is_constructor,
                        "is_async": fn.is_async,
                        "is_static": fn.is_static,
                        "is_class_method": fn.is_class_method,
                        "visibility": fn.visibility.value,
                        "parameters": json.dumps(fn.parameters),
                        "return_type": fn.return_type,
                        "start_line": fn.start_line,
                        "end_line": fn.end_line,
                        "language": fn.language,
                        "documentation": fn.documentation,
                        "decorators": json.dumps(fn.decorators),
                        "signature": fn.signature,
                    }
                    for fn in summary.functions
                ],
            )

        # ── Routes ────────────────────────────────────────────────────────────
        if summary.routes:
            await self._session.execute(
                RouteRecord.__table__.insert(),
                [
                    {
                        "id": r.id,
                        "repository_id": rid,
                        "file_id": fid,
                        "http_method": r.http_method,
                        "path": r.path,
                        "handler_name": r.handler_name,
                        "framework": r.framework,
                        "start_line": r.start_line,
                        "language": r.language,
                    }
                    for r in summary.routes
                ],
            )

        await self._session.flush()

    # ── Query operations ──────────────────────────────────────────────────────

    async def get_symbols(
        self,
        repository_id: uuid.UUID,
        symbol_type: SymbolType | None = None,
        language: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[Symbol]:
        """Query symbols for a repository with optional filters.

        Args:
            repository_id: Repository UUID.
            symbol_type: Optional type filter.
            language: Optional language filter.
            limit: Maximum rows to return.
            offset: Row offset for pagination.

        Returns:
            List of :class:`~backend.app.models.symbol.Symbol` instances.
        """
        stmt = (
            select(Symbol)
            .where(Symbol.repository_id == repository_id)
            .order_by(Symbol.qualified_name)
            .limit(limit)
            .offset(offset)
        )
        if symbol_type:
            stmt = stmt.where(Symbol.symbol_type == symbol_type)
        if language:
            stmt = stmt.where(Symbol.language == language)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_classes(
        self,
        repository_id: uuid.UUID,
        language: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[ClassRecord]:
        """Query class definitions for a repository.

        Args:
            repository_id: Repository UUID.
            language: Optional language filter.
            limit: Maximum rows.
            offset: Row offset.

        Returns:
            List of :class:`~backend.app.models.symbol.ClassRecord` instances.
        """
        stmt = (
            select(ClassRecord)
            .where(ClassRecord.repository_id == repository_id)
            .order_by(ClassRecord.qualified_name)
            .limit(limit)
            .offset(offset)
        )
        if language:
            stmt = stmt.where(ClassRecord.language == language)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_functions(
        self,
        repository_id: uuid.UUID,
        language: str | None = None,
        is_method: bool | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[FunctionRecord]:
        """Query function/method definitions for a repository.

        Args:
            repository_id: Repository UUID.
            language: Optional language filter.
            is_method: When True return only methods; False returns only functions.
            limit: Maximum rows.
            offset: Row offset.

        Returns:
            List of :class:`~backend.app.models.symbol.FunctionRecord` instances.
        """
        stmt = (
            select(FunctionRecord)
            .where(FunctionRecord.repository_id == repository_id)
            .order_by(FunctionRecord.qualified_name)
            .limit(limit)
            .offset(offset)
        )
        if language:
            stmt = stmt.where(FunctionRecord.language == language)
        if is_method is not None:
            stmt = stmt.where(FunctionRecord.is_method == is_method)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_routes(
        self,
        repository_id: uuid.UUID,
        http_method: str | None = None,
        framework: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[RouteRecord]:
        """Query route definitions for a repository.

        Args:
            repository_id: Repository UUID.
            http_method: Optional HTTP verb filter (e.g. ``"GET"``).
            framework: Optional framework filter (e.g. ``"fastapi"``).
            limit: Maximum rows.
            offset: Row offset.

        Returns:
            List of :class:`~backend.app.models.symbol.RouteRecord` instances.
        """
        stmt = (
            select(RouteRecord)
            .where(RouteRecord.repository_id == repository_id)
            .order_by(RouteRecord.path, RouteRecord.http_method)
            .limit(limit)
            .offset(offset)
        )
        if http_method:
            stmt = stmt.where(RouteRecord.http_method == http_method.upper())
        if framework:
            stmt = stmt.where(RouteRecord.framework == framework.lower())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_symbols(self, repository_id: uuid.UUID) -> int:
        """Count total symbols for a repository.

        Args:
            repository_id: Repository UUID.

        Returns:
            Integer count.
        """
        result = await self._session.execute(
            select(func.count(Symbol.id)).where(Symbol.repository_id == repository_id)
        )
        return result.scalar_one()
