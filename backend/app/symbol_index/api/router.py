"""Symbol Intelligence Engine REST API endpoints.

Exposes the full Symbol Index lifecycle:

    POST  /repositories/{id}/symbols/index
        Enqueues asynchronous symbol indexing.

    GET   /repositories/{id}/symbols/index/progress
        Returns current indexing progress.

    GET   /repositories/{id}/symbols/index/entries
        Lists all index entries with filters.

    GET   /repositories/{id}/symbols/index/entries/{symbol_id}
        Returns a single symbol entry by UUID.

    GET   /repositories/{id}/symbols/index/search
        Searches index entries by name or qualified name.

All responses use the unified :class:`~backend.app.schemas.base.APIResponse`
envelope.  The POST endpoint returns immediately with status ``QUEUED`` and
dispatches work to a Celery background task (FastAPI BackgroundTasks fallback).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Query, status

from backend.app.core.exceptions import NotFoundError
from backend.app.core.logging import get_logger
from backend.app.dependencies.database import DBSession
from backend.app.schemas.base import APIResponse
from backend.app.symbol_index.schemas.index import (
    IndexInitiatedResponse,
    IndexProgressResponse,
    SymbolIndexEntryResponse,
    SymbolIndexListResponse,
    SymbolIndexSearchRequest,
    SymbolIndexSearchResponse,
)
from backend.app.symbol_index.services.index_service import SymbolIndexService
from backend.app.symbol_index.repositories.index_repository import SymbolIndexRepository

logger = get_logger(__name__)

router = APIRouter(tags=["Symbol Intelligence Engine"])


# ── POST /repositories/{id}/symbols/index ─────────────────────────────────────


@router.post(
    "/repositories/{repository_id}/symbols/index",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=APIResponse[IndexInitiatedResponse],
    summary="Start symbol indexing",
    description=(
        "Enqueues an asynchronous symbol-indexing pipeline that reads all "
        "parsed source files, extracts canonical symbol information, generates "
        "fully-qualified names, and writes them to the Symbol Index. "
        "Returns immediately with ``status=QUEUED``. "
        "Poll ``GET .../symbols/index/progress`` to track completion. "
        "The repository must have ``clone_status=READY``. "
        "The parser (``POST .../parse``) should be run first."
    ),
    responses={
        202: {"description": "Indexing accepted and enqueued"},
        404: {"description": "Repository not found"},
        409: {"description": "Repository is not in READY state"},
    },
)
async def start_symbol_index(
    repository_id: uuid.UUID,
    db: DBSession,
    background_tasks: BackgroundTasks,
) -> APIResponse[IndexInitiatedResponse]:
    """Enqueue symbol indexing for a repository.

    Args:
        repository_id: The UUID path parameter.
        db: Injected SQLAlchemy async session.
        background_tasks: FastAPI background task queue (Celery fallback).

    Returns:
        APIResponse wrapping :class:`IndexInitiatedResponse`.
    """
    _enqueue_index(repository_id, background_tasks)

    result = IndexInitiatedResponse(
        repository_id=repository_id,
        status="QUEUED",
        message=(
            "Symbol indexing enqueued. "
            "Poll GET .../symbols/index/progress to track completion."
        ),
    )

    logger.info(
        "Symbol index accepted",
        repository_id=str(repository_id),
    )
    return APIResponse.ok(
        data=result,
        message="Symbol indexing has been enqueued.",
    )


# ── GET /repositories/{id}/symbols/index/progress ─────────────────────────────


@router.get(
    "/repositories/{repository_id}/symbols/index/progress",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[IndexProgressResponse],
    summary="Get symbol indexing progress",
    description="Returns the current symbol-indexing progress for a repository.",
    responses={404: {"description": "Repository not found"}},
)
async def get_index_progress(
    repository_id: uuid.UUID,
    db: DBSession,
) -> APIResponse[IndexProgressResponse]:
    """Return symbol-index progress for a repository.

    Args:
        repository_id: The UUID path parameter.
        db: Injected SQLAlchemy async session.

    Returns:
        APIResponse wrapping :class:`IndexProgressResponse`.
    """
    service = SymbolIndexService(session=db)
    progress = await service.get_progress(repository_id)
    return APIResponse.ok(data=progress, message="Index progress retrieved.")


# ── GET /repositories/{id}/symbols/index/entries ──────────────────────────────


@router.get(
    "/repositories/{repository_id}/symbols/index/entries",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[SymbolIndexListResponse],
    summary="List symbol index entries",
    description=(
        "Returns a paginated list of canonical symbol index entries for a "
        "repository. Supports filtering by language, symbol_type, and file_id."
    ),
)
async def list_index_entries(
    repository_id: uuid.UUID,
    db: DBSession,
    language: str | None = Query(default=None, description="Filter by language"),
    symbol_type: str | None = Query(default=None, description="Filter by symbol type"),
    filename: str | None = Query(default=None, description="Filter by source filename (substring match)"),
    limit: int = Query(default=100, ge=1, le=2000, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Row offset"),
) -> APIResponse[SymbolIndexListResponse]:
    """List canonical symbol index entries for a repository.

    Args:
        repository_id: Repository UUID.
        db: Injected database session.
        language: Optional language filter.
        symbol_type: Optional symbol-type filter.
        filename: Optional filename substring filter.
        limit: Page size.
        offset: Row offset.

    Returns:
        APIResponse wrapping :class:`SymbolIndexListResponse`.
    """
    index_repo = SymbolIndexRepository(session=db)

    # Resolve file_id from filename if provided
    file_uuid: uuid.UUID | None = None
    if filename:
        from backend.app.repositories.file_repository import FileRepository  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415
        from backend.app.models.file import RepositoryFile  # noqa: PLC0415
        from sqlalchemy import func  # noqa: PLC0415

        result = await db.execute(
            select(RepositoryFile.id).where(
                RepositoryFile.repository_id == repository_id,
                func.lower(RepositoryFile.file_name).contains(filename.lower()),
            ).limit(1)
        )
        row = result.scalar_one_or_none()
        file_uuid = row if row else None

    entries = await index_repo.list_entries(
        repository_id,
        language=language,
        symbol_type=symbol_type,
        file_id=file_uuid,
        limit=limit,
        offset=offset,
    )
    total = await index_repo.count_entries(
        repository_id,
        language=language,
        symbol_type=symbol_type,
    )

    items = [SymbolIndexEntryResponse.model_validate(e) for e in entries]
    return APIResponse.ok(
        data=SymbolIndexListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        ),
        message=f"Retrieved {len(items)} symbol index entries.",
    )


# ── GET /repositories/{id}/symbols/index/entries/{symbol_id} ──────────────────


@router.get(
    "/repositories/{repository_id}/symbols/index/entries/{symbol_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[SymbolIndexEntryResponse],
    summary="Get symbol by ID",
    description="Returns a single canonical symbol index entry by its UUID.",
    responses={
        404: {"description": "Symbol not found"},
    },
)
async def get_index_entry(
    repository_id: uuid.UUID,
    symbol_id: uuid.UUID,
    db: DBSession,
) -> APIResponse[SymbolIndexEntryResponse]:
    """Retrieve a single symbol index entry.

    Args:
        repository_id: Repository UUID (used for access scope validation).
        symbol_id: Symbol UUID.
        db: Injected database session.

    Returns:
        APIResponse wrapping :class:`SymbolIndexEntryResponse`.
    """
    index_repo = SymbolIndexRepository(session=db)
    entry = await index_repo.get_entry_by_id(symbol_id)

    if entry is None or entry.repository_id != repository_id:
        raise NotFoundError("SymbolIndexEntry", str(symbol_id))

    return APIResponse.ok(
        data=SymbolIndexEntryResponse.model_validate(entry),
        message="Symbol index entry retrieved.",
    )


# ── GET /repositories/{id}/symbols/index/search ───────────────────────────────


@router.get(
    "/repositories/{repository_id}/symbols/index/search",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[SymbolIndexSearchResponse],
    summary="Search symbol index",
    description=(
        "Searches the Symbol Index by name or qualified name. "
        "Supported modes: ``prefix`` (default), ``exact``, ``qualified``."
    ),
)
async def search_index(
    repository_id: uuid.UUID,
    db: DBSession,
    q: str = Query(
        min_length=1,
        max_length=512,
        description="Search query (name or qualified name fragment)",
    ),
    mode: str = Query(
        default="prefix",
        description="Search mode: prefix | exact | qualified",
    ),
    language: str | None = Query(default=None, description="Filter by language"),
    symbol_type: str | None = Query(default=None, description="Filter by symbol type"),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum results"),
) -> APIResponse[SymbolIndexSearchResponse]:
    """Search the Symbol Index.

    Args:
        repository_id: Repository UUID.
        db: Injected database session.
        q: Search query string.
        mode: Search mode (prefix | exact | qualified).
        language: Optional language filter.
        symbol_type: Optional symbol-type filter.
        limit: Maximum results.

    Returns:
        APIResponse wrapping :class:`SymbolIndexSearchResponse`.
    """
    # Validate mode
    valid_modes = {"prefix", "exact", "qualified"}
    if mode not in valid_modes:
        mode = "prefix"

    index_repo = SymbolIndexRepository(session=db)
    results = await index_repo.search_entries(
        repository_id,
        query=q,
        mode=mode,
        language=language,
        symbol_type=symbol_type,
        limit=limit,
    )

    items = [SymbolIndexEntryResponse.model_validate(e) for e in results]
    return APIResponse.ok(
        data=SymbolIndexSearchResponse(
            query=q,
            mode=mode,
            items=items,
            total=len(items),
        ),
        message=f"Found {len(items)} symbols matching '{q}'.",
    )


# ── Enqueue helper ─────────────────────────────────────────────────────────────


def _enqueue_index(
    repository_id: uuid.UUID,
    background_tasks: BackgroundTasks,
) -> None:
    """Dispatch the symbol-index task to Celery, or fall back to BackgroundTasks.

    Args:
        repository_id: UUID of the repository to index.
        background_tasks: FastAPI background task queue (fallback path).
    """
    try:
        from backend.app.symbol_index.workers.index_tasks import index_repository_task  # noqa: PLC0415

        index_repository_task.delay(str(repository_id))
        logger.info(
            "Symbol index task dispatched to Celery",
            repository_id=str(repository_id),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Celery unavailable; falling back to FastAPI BackgroundTasks",
            repository_id=str(repository_id),
            error=str(exc),
        )
        background_tasks.add_task(_run_index_in_background, repository_id)


async def _run_index_in_background(repository_id: uuid.UUID) -> None:
    """BackgroundTasks fallback: run the symbol-index pipeline in-process.

    Args:
        repository_id: UUID of the repository to index.
    """
    from backend.app.db.session import get_session_context  # noqa: PLC0415

    async with get_session_context() as session:
        service = SymbolIndexService(session=session)
        try:
            await service.index_repository(repository_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "BackgroundTask symbol index pipeline raised",
                repository_id=str(repository_id),
                error=str(exc),
            )
