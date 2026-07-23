"""Code Intelligence Engine API endpoints.

Exposes parse operations and symbol queries:

    POST   /api/v1/repositories/{id}/parse       — Enqueue parse job
    GET    /api/v1/repositories/{id}/parse/progress — Parse progress
    GET    /api/v1/repositories/{id}/symbols     — List symbols
    GET    /api/v1/repositories/{id}/classes     — List classes
    GET    /api/v1/repositories/{id}/functions   — List functions
    GET    /api/v1/repositories/{id}/routes      — List HTTP routes

All responses use the unified :class:`~backend.app.schemas.base.APIResponse`
envelope. Parse is deferred to a Celery background task; the POST endpoint
returns immediately with status ``QUEUED``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Query, status

from backend.app.core.logging import get_logger
from backend.app.dependencies.database import DBSession
from backend.app.repositories.symbol_repository import SymbolRepository
from backend.app.schemas.base import APIResponse
from backend.app.schemas.parser import (
    ClassListResponse,
    ClassResponse,
    FunctionListResponse,
    FunctionResponse,
    ParseInitiatedResponse,
    ParseProgressResponse,
    RouteListResponse,
    RouteResponse,
    SymbolListResponse,
    SymbolResponse,
)
from backend.app.services.parser_service import RepositoryParserService

logger = get_logger(__name__)

router = APIRouter(tags=["Code Intelligence"])


# ── POST /repositories/{id}/parse ─────────────────────────────────────────────


@router.post(
    "/repositories/{repository_id}/parse",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=APIResponse[ParseInitiatedResponse],
    summary="Parse a repository",
    description=(
        "Enqueues an asynchronous AST parse pipeline that analyses all "
        "supported source files and builds a complete symbol database. "
        "Returns immediately with ``status=QUEUED``. "
        "Poll ``GET /repositories/{id}/parse/progress`` to check progress."
    ),
    responses={
        202: {"description": "Parse accepted and enqueued"},
        404: {"description": "Repository not found"},
        409: {"description": "Repository is not in READY state"},
    },
)
async def parse_repository(
    repository_id: uuid.UUID,
    db: DBSession,
    background_tasks: BackgroundTasks,
) -> APIResponse[ParseInitiatedResponse]:
    """Enqueue repository AST parsing.

    Args:
        repository_id: The UUID path parameter.
        db: Injected SQLAlchemy async session.
        background_tasks: FastAPI background task queue (Celery fallback).

    Returns:
        APIResponse wrapping :class:`ParseInitiatedResponse`.
    """
    _enqueue_parse(repository_id, background_tasks)

    result = ParseInitiatedResponse(
        repository_id=repository_id,
        status="QUEUED",
        message="Parse enqueued. Poll /parse/progress to track completion.",
    )

    logger.info("Repository parse accepted", repository_id=str(repository_id))
    return APIResponse.ok(data=result, message="Repository parse has been enqueued.")


# ── GET /repositories/{id}/parse/progress ─────────────────────────────────────


@router.get(
    "/repositories/{repository_id}/parse/progress",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ParseProgressResponse],
    summary="Get parse progress",
    description="Returns the current parse progress for a repository.",
    responses={404: {"description": "Repository not found"}},
)
async def get_parse_progress(
    repository_id: uuid.UUID,
    db: DBSession,
) -> APIResponse[ParseProgressResponse]:
    """Return parse progress.

    Args:
        repository_id: The UUID path parameter.
        db: Injected SQLAlchemy async session.

    Returns:
        APIResponse wrapping :class:`ParseProgressResponse`.
    """
    service = RepositoryParserService(session=db)
    progress = await service.get_parse_progress(repository_id)
    return APIResponse.ok(data=progress, message="Parse progress retrieved.")


# ── GET /repositories/{id}/symbols ────────────────────────────────────────────


@router.get(
    "/repositories/{repository_id}/symbols",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[SymbolListResponse],
    summary="List symbols",
    description="Returns all extracted code symbols for a repository.",
)
async def list_symbols(
    repository_id: uuid.UUID,
    db: DBSession,
    symbol_type: str | None = Query(default=None, description="Filter by symbol type"),
    language: str | None = Query(default=None, description="Filter by language"),
    limit: int = Query(default=500, ge=1, le=2000, description="Maximum results"),
    offset: int = Query(default=0, ge=0, description="Row offset for pagination"),
) -> APIResponse[SymbolListResponse]:
    """List code symbols for a repository.

    Args:
        repository_id: Repository UUID.
        db: Injected database session.
        symbol_type: Optional symbol type filter.
        language: Optional language filter.
        limit: Page size.
        offset: Page offset.

    Returns:
        APIResponse wrapping :class:`SymbolListResponse`.
    """
    from backend.app.models.symbol import SymbolType as ST  # noqa: PLC0415

    sym_repo = SymbolRepository(session=db)
    stype = None
    if symbol_type:
        try:
            stype = ST(symbol_type.lower())
        except ValueError:
            stype = None

    symbols = await sym_repo.get_symbols(
        repository_id, symbol_type=stype, language=language,
        limit=limit, offset=offset,
    )
    total = await sym_repo.count_symbols(repository_id)
    items = [SymbolResponse.model_validate(s) for s in symbols]
    return APIResponse.ok(
        data=SymbolListResponse(items=items, total=total, limit=limit, offset=offset),
        message=f"Retrieved {len(items)} symbols.",
    )


# ── GET /repositories/{id}/classes ────────────────────────────────────────────


@router.get(
    "/repositories/{repository_id}/classes",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[ClassListResponse],
    summary="List classes",
    description="Returns all extracted class definitions for a repository.",
)
async def list_classes(
    repository_id: uuid.UUID,
    db: DBSession,
    language: str | None = Query(default=None, description="Filter by language"),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> APIResponse[ClassListResponse]:
    """List class definitions for a repository.

    Args:
        repository_id: Repository UUID.
        db: Injected database session.
        language: Optional language filter.
        limit: Page size.
        offset: Page offset.

    Returns:
        APIResponse wrapping :class:`ClassListResponse`.
    """
    sym_repo = SymbolRepository(session=db)
    classes = await sym_repo.get_classes(
        repository_id, language=language, limit=limit, offset=offset
    )
    items = [ClassResponse.model_validate(c) for c in classes]
    return APIResponse.ok(
        data=ClassListResponse(items=items, total=len(items), limit=limit, offset=offset),
        message=f"Retrieved {len(items)} classes.",
    )


# ── GET /repositories/{id}/functions ──────────────────────────────────────────


@router.get(
    "/repositories/{repository_id}/functions",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[FunctionListResponse],
    summary="List functions",
    description="Returns all extracted function and method definitions.",
)
async def list_functions(
    repository_id: uuid.UUID,
    db: DBSession,
    language: str | None = Query(default=None, description="Filter by language"),
    is_method: bool | None = Query(default=None, description="True=methods only, False=functions only"),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> APIResponse[FunctionListResponse]:
    """List function definitions for a repository.

    Args:
        repository_id: Repository UUID.
        db: Injected database session.
        language: Optional language filter.
        is_method: Optional method/function filter.
        limit: Page size.
        offset: Page offset.

    Returns:
        APIResponse wrapping :class:`FunctionListResponse`.
    """
    sym_repo = SymbolRepository(session=db)
    functions = await sym_repo.get_functions(
        repository_id, language=language, is_method=is_method,
        limit=limit, offset=offset,
    )
    items = [FunctionResponse.model_validate(f) for f in functions]
    return APIResponse.ok(
        data=FunctionListResponse(items=items, total=len(items), limit=limit, offset=offset),
        message=f"Retrieved {len(items)} functions.",
    )


# ── GET /repositories/{id}/routes ─────────────────────────────────────────────


@router.get(
    "/repositories/{repository_id}/routes",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RouteListResponse],
    summary="List HTTP routes",
    description="Returns all detected HTTP route/endpoint definitions.",
)
async def list_routes(
    repository_id: uuid.UUID,
    db: DBSession,
    http_method: str | None = Query(default=None, description="Filter by HTTP verb (GET, POST, …)"),
    framework: str | None = Query(default=None, description="Filter by framework (fastapi, express, …)"),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> APIResponse[RouteListResponse]:
    """List HTTP routes for a repository.

    Args:
        repository_id: Repository UUID.
        db: Injected database session.
        http_method: Optional HTTP verb filter.
        framework: Optional framework filter.
        limit: Page size.
        offset: Page offset.

    Returns:
        APIResponse wrapping :class:`RouteListResponse`.
    """
    sym_repo = SymbolRepository(session=db)
    routes = await sym_repo.get_routes(
        repository_id, http_method=http_method, framework=framework,
        limit=limit, offset=offset,
    )
    items = [RouteResponse.model_validate(r) for r in routes]
    return APIResponse.ok(
        data=RouteListResponse(items=items, total=len(items), limit=limit, offset=offset),
        message=f"Retrieved {len(items)} routes.",
    )


# ── Enqueue helper ─────────────────────────────────────────────────────────────


def _enqueue_parse(repository_id: uuid.UUID, background_tasks: BackgroundTasks) -> None:
    """Dispatch the parse task to Celery, or fall back to BackgroundTasks.

    Args:
        repository_id: UUID of the repository to parse.
        background_tasks: FastAPI background task queue (fallback).
    """
    try:
        from backend.app.workers.parser_tasks import parse_repository_task  # noqa: PLC0415

        parse_repository_task.delay(str(repository_id))
        logger.info("Parse task dispatched to Celery", repository_id=str(repository_id))
    except Exception as exc:
        logger.warning(
            "Celery unavailable; falling back to FastAPI BackgroundTasks",
            repository_id=str(repository_id),
            error=str(exc),
        )
        background_tasks.add_task(_run_parse_in_background, repository_id)


async def _run_parse_in_background(repository_id: uuid.UUID) -> None:
    """BackgroundTasks fallback: run parse pipeline in-process.

    Args:
        repository_id: UUID of the repository to parse.
    """
    from backend.app.db.session import get_session_context  # noqa: PLC0415

    async with get_session_context() as session:
        service = RepositoryParserService(session=session)
        try:
            await service.parse_repository(repository_id)
        except Exception as exc:
            logger.error(
                "BackgroundTask parse pipeline raised",
                repository_id=str(repository_id),
                error=str(exc),
            )
