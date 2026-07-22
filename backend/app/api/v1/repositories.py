"""Repository Management API endpoints.

Exposes the four core operations over GitHub repositories:

    POST   /api/v1/repositories          — Register & enqueue clone
    GET    /api/v1/repositories          — List all repositories
    GET    /api/v1/repositories/{id}     — Get single repository detail
    DELETE /api/v1/repositories/{id}     — Delete record + local clone

All responses use the unified :class:`~backend.app.schemas.base.APIResponse`
envelope. Cloning is deferred to a Celery background task so the POST
endpoint returns immediately with status ``PENDING``.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, status

from backend.app.core.logging import get_logger
from backend.app.dependencies.database import DBSession
from backend.app.schemas.base import APIResponse
from backend.app.schemas.repository import (
    RepositoryCreateRequest,
    RepositoryCreateResponse,
    RepositoryListResponse,
    RepositoryResponse,
)
from backend.app.services.repository_service import RepositoryService

logger = get_logger(__name__)

router = APIRouter(prefix="/repositories", tags=["Repository Management"])


# ── POST /repositories ─────────────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=APIResponse[RepositoryCreateResponse],
    summary="Register a GitHub repository",
    description=(
        "Validates the GitHub URL, creates a PENDING repository record, and "
        "enqueues an asynchronous clone-and-metadata pipeline. "
        "Returns immediately with ``status=PENDING``. "
        "Poll ``GET /repositories/{id}`` to check progress."
    ),
    responses={
        202: {"description": "Repository accepted and clone enqueued"},
        409: {"description": "Repository already registered (use reclone=true to force)"},
        422: {"description": "Invalid GitHub URL or request payload"},
        403: {"description": "Repository is private or inaccessible"},
    },
)
async def create_repository(
    request: RepositoryCreateRequest,
    db: DBSession,
    background_tasks: BackgroundTasks,
) -> APIResponse[RepositoryCreateResponse]:
    """Register a GitHub repository and kick off the clone pipeline.

    Args:
        request: JSON body with ``github_url`` and optional ``reclone`` flag.
        db: Injected SQLAlchemy async session.
        background_tasks: FastAPI background task queue.

    Returns:
        APIResponse wrapping :class:`RepositoryCreateResponse` (id + status).
    """
    service = RepositoryService(session=db)
    result = await service.create_repository(request)

    # Enqueue clone pipeline.  We try Celery first; if it is unavailable
    # (e.g. local dev without a worker) we fall back to FastAPI BackgroundTasks.
    _enqueue_clone(result.id, background_tasks)

    logger.info(
        "Repository accepted",
        repository_id=str(result.id),
        github_url=request.github_url,
    )

    return APIResponse.ok(
        data=result,
        message="Repository accepted. Cloning has been enqueued.",
    )


# ── GET /repositories ──────────────────────────────────────────────────────────


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RepositoryListResponse],
    summary="List all repositories",
    description="Returns all registered repositories ordered by creation time (newest first).",
)
async def list_repositories(
    db: DBSession,
) -> APIResponse[RepositoryListResponse]:
    """Retrieve all registered repositories.

    Args:
        db: Injected SQLAlchemy async session.

    Returns:
        APIResponse wrapping :class:`RepositoryListResponse`.
    """
    service = RepositoryService(session=db)
    result = await service.list_repositories()
    return APIResponse.ok(
        data=result,
        message=f"Retrieved {result.total} repositories.",
    )


# ── GET /repositories/{id} ─────────────────────────────────────────────────────


@router.get(
    "/{repository_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[RepositoryResponse],
    summary="Get repository details",
    description="Returns full metadata and clone status for a single repository.",
    responses={
        404: {"description": "Repository not found"},
    },
)
async def get_repository(
    repository_id: uuid.UUID,
    db: DBSession,
) -> APIResponse[RepositoryResponse]:
    """Retrieve a single repository by its UUID.

    Args:
        repository_id: The UUID path parameter.
        db: Injected SQLAlchemy async session.

    Returns:
        APIResponse wrapping :class:`RepositoryResponse`.
    """
    service = RepositoryService(session=db)
    result = await service.get_repository(repository_id)
    return APIResponse.ok(data=result, message="Repository retrieved successfully.")


# ── DELETE /repositories/{id} ──────────────────────────────────────────────────


@router.delete(
    "/{repository_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[None],
    summary="Delete a repository",
    description=(
        "Removes the database record and deletes the local clone directory. "
        "This operation is irreversible."
    ),
    responses={
        404: {"description": "Repository not found"},
    },
)
async def delete_repository(
    repository_id: uuid.UUID,
    db: DBSession,
) -> APIResponse[None]:
    """Delete a repository record and its cloned files.

    Args:
        repository_id: The UUID path parameter.
        db: Injected SQLAlchemy async session.

    Returns:
        APIResponse with ``data=null`` and a confirmation message.
    """
    service = RepositoryService(session=db)
    await service.delete_repository(repository_id)
    return APIResponse.ok(data=None, message="Repository deleted successfully.")


# ── Enqueue helper ─────────────────────────────────────────────────────────────


def _enqueue_clone(repository_id: uuid.UUID, background_tasks: BackgroundTasks) -> None:
    """Dispatch the clone task to Celery, or fall back to FastAPI BackgroundTasks.

    Celery is preferred for production because workers can be scaled
    independently and tasks survive API restarts.  The fallback ensures
    the clone still runs in local development without a Celery worker.

    Args:
        repository_id: UUID of the repository to clone.
        background_tasks: FastAPI background task queue (fallback path).
    """
    try:
        from backend.app.workers.celery_app import clone_repository_task  # noqa: PLC0415

        clone_repository_task.delay(str(repository_id))
        logger.info(
            "Clone task dispatched to Celery",
            repository_id=str(repository_id),
        )
    except Exception as exc:
        logger.warning(
            "Celery unavailable; falling back to FastAPI BackgroundTasks",
            repository_id=str(repository_id),
            error=str(exc),
        )
        background_tasks.add_task(_run_pipeline_in_background, repository_id)


async def _run_pipeline_in_background(repository_id: uuid.UUID) -> None:
    """BackgroundTasks fallback: run the clone pipeline in-process.

    Creates its own service instance and session via the
    ``run_clone_pipeline`` method which opens an internal session context.

    Args:
        repository_id: UUID of the repository to clone.
    """
    service = RepositoryService(session=None)  # type: ignore[arg-type]
    try:
        await service.run_clone_pipeline(repository_id)
    except Exception as exc:
        # Already logged + marked FAILED inside run_clone_pipeline
        logger.error(
            "BackgroundTask clone pipeline raised",
            repository_id=str(repository_id),
            error=str(exc),
        )
