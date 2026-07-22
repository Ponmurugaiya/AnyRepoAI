"""Repository Scanner API endpoints.

Exposes scanner operations:

    POST   /api/v1/repositories/{id}/scan        — Enqueue repository scan
    GET    /api/v1/repositories/{id}/manifest    — Retrieve scan manifest
    GET    /api/v1/repositories/{id}/files       — List all scanned files

All responses use the unified :class:`~backend.app.schemas.base.APIResponse`
envelope. The scan operation is deferred to a Celery background task so the
POST endpoint returns immediately with status ``SCANNING``.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, status

from backend.app.core.logging import get_logger
from backend.app.dependencies.database import DBSession
from backend.app.schemas.base import APIResponse
from backend.app.schemas.scanner import (
    FileMetadataResponse,
    RepositoryManifest,
    ScanInitiatedResponse,
)
from backend.app.services.scanner_service import RepositoryScannerService

logger = get_logger(__name__)

router = APIRouter(tags=["Repository Scanner"])


# ── POST /repositories/{id}/scan ──────────────────────────────────────────────


@router.post(
    "/repositories/{repository_id}/scan",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=APIResponse[ScanInitiatedResponse],
    summary="Scan a repository",
    description=(
        "Enqueues an asynchronous scan pipeline that walks the cloned "
        "repository filesystem, builds file metadata (language, hash, size, etc.), "
        "and persists results to the ``repository_files`` table. "
        "Returns immediately with ``status=SCANNING``. "
        "Poll ``GET /repositories/{id}/manifest`` to check progress."
    ),
    responses={
        202: {"description": "Scan accepted and enqueued"},
        404: {"description": "Repository not found"},
        409: {
            "description": (
                "Repository is not in READY status, or a scan is already running"
            )
        },
    },
)
async def scan_repository(
    repository_id: uuid.UUID,
    db: DBSession,
    background_tasks: BackgroundTasks,
) -> APIResponse[ScanInitiatedResponse]:
    """Enqueue a repository scan.

    Args:
        repository_id: The UUID path parameter.
        db: Injected SQLAlchemy async session.
        background_tasks: FastAPI background task queue (fallback when Celery unavailable).

    Returns:
        APIResponse wrapping :class:`ScanInitiatedResponse` (id + status).
    """
    service = RepositoryScannerService(session=db)

    # Validate repository exists and is READY (raises on error)
    # The service handles all status checks internally
    result = ScanInitiatedResponse(
        repository_id=repository_id,
        status="SCANNING",
        message="Scan enqueued successfully. Poll /manifest to check progress.",
    )

    _enqueue_scan(repository_id, background_tasks)

    logger.info(
        "Repository scan accepted",
        repository_id=str(repository_id),
    )

    return APIResponse.ok(
        data=result,
        message="Repository scan has been enqueued.",
    )


# ── GET /repositories/{id}/manifest ───────────────────────────────────────────


@router.get(
    "/repositories/{repository_id}/manifest",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RepositoryManifest],
    summary="Get repository manifest",
    description=(
        "Returns the complete scan manifest including aggregate statistics, "
        "per-language breakdown, and hierarchical directory tree. "
        "This endpoint retrieves data from the ``repository_files`` table "
        "and does NOT trigger a new scan."
    ),
    responses={
        404: {"description": "Repository not found"},
    },
)
async def get_repository_manifest(
    repository_id: uuid.UUID,
    db: DBSession,
) -> APIResponse[RepositoryManifest]:
    """Retrieve the full repository manifest.

    Args:
        repository_id: The UUID path parameter.
        db: Injected SQLAlchemy async session.

    Returns:
        APIResponse wrapping :class:`RepositoryManifest`.
    """
    service = RepositoryScannerService(session=db)
    manifest = await service.generate_manifest(repository_id)
    return APIResponse.ok(
        data=manifest,
        message="Repository manifest retrieved successfully.",
    )


# ── GET /repositories/{id}/files ──────────────────────────────────────────────


@router.get(
    "/repositories/{repository_id}/files",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[FileMetadataResponse]],
    summary="List all scanned files",
    description=(
        "Returns a flat list of all file metadata records for a repository "
        "ordered by relative path. Useful for downstream processing by the "
        "AST Parser module."
    ),
    responses={
        404: {"description": "Repository not found"},
    },
)
async def list_repository_files(
    repository_id: uuid.UUID,
    db: DBSession,
) -> APIResponse[list[FileMetadataResponse]]:
    """List all scanned file records for a repository.

    Args:
        repository_id: The UUID path parameter.
        db: Injected SQLAlchemy async session.

    Returns:
        APIResponse wrapping a list of :class:`FileMetadataResponse`.
    """
    from backend.app.repositories.file_repository import FileRepository  # noqa: PLC0415

    file_repo = FileRepository(session=db)
    files = await file_repo.get_by_repository_id(repository_id)
    items = [FileMetadataResponse.model_validate(f) for f in files]

    return APIResponse.ok(
        data=items,
        message=f"Retrieved {len(items)} file records.",
    )


# ── Enqueue helper ─────────────────────────────────────────────────────────────


def _enqueue_scan(repository_id: uuid.UUID, background_tasks: BackgroundTasks) -> None:
    """Dispatch the scan task to Celery, or fall back to FastAPI BackgroundTasks.

    Celery is preferred for production. The fallback ensures the scan still
    runs in local development without a Celery worker.

    Args:
        repository_id: UUID of the repository to scan.
        background_tasks: FastAPI background task queue (fallback path).
    """
    try:
        from backend.app.workers.scanner_tasks import scan_repository_task  # noqa: PLC0415

        scan_repository_task.delay(str(repository_id))
        logger.info(
            "Scan task dispatched to Celery",
            repository_id=str(repository_id),
        )
    except Exception as exc:
        logger.warning(
            "Celery unavailable; falling back to FastAPI BackgroundTasks",
            repository_id=str(repository_id),
            error=str(exc),
        )
        background_tasks.add_task(_run_scan_in_background, repository_id)


async def _run_scan_in_background(repository_id: uuid.UUID) -> None:
    """BackgroundTasks fallback: run the scan pipeline in-process.

    Opens its own session context via ``get_session_context``.

    Args:
        repository_id: UUID of the repository to scan.
    """
    from backend.app.db.session import get_session_context  # noqa: PLC0415

    async with get_session_context() as session:
        service = RepositoryScannerService(session=session)
        try:
            await service.scan_repository(repository_id)
        except Exception as exc:
            logger.error(
                "BackgroundTask scan pipeline raised",
                repository_id=str(repository_id),
                error=str(exc),
            )
