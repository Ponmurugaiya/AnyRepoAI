"""Celery application factory and task definitions.

The Celery app uses Redis as both the broker and result backend,
matching the Redis service already running in docker-compose.

Tasks:
    clone_repository_task: Runs the full clone-and-metadata pipeline
                           for a single repository identified by UUID.
"""

import asyncio
import uuid

from celery import Celery
from celery.utils.log import get_task_logger

from backend.app.core.config import get_settings

logger = get_task_logger(__name__)


def _make_celery() -> Celery:
    """Create and configure the Celery application.

    Broker and result backend are derived from the application's
    Redis settings so configuration stays in one place.

    Returns:
        Celery: Configured Celery application instance.
    """
    settings = get_settings()

    app = Celery(
        "codebase_intel",
        broker=settings.redis.url,
        backend=settings.redis.url,
        include=[
            "backend.app.workers.celery_app",
            "backend.app.workers.scanner_tasks",
            "backend.app.workers.parser_tasks",
            "backend.app.symbol_index.workers.index_tasks",
        ],
    )

    app.conf.update(
        # Serialisation
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # Timezone
        timezone="UTC",
        enable_utc=True,
        # Reliability
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        # Result expiry — 24 hours
        result_expires=86_400,
        # Retry policy defaults
        task_default_retry_delay=30,
        task_max_retries=3,
    )

    return app


celery_app = _make_celery()


@celery_app.task(
    bind=True,
    name="repository.clone",
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
)
def clone_repository_task(self, repository_id: str) -> dict:
    """Celery task: clone a repository and extract its metadata.

    Delegates the actual work to :meth:`RepositoryService.run_clone_pipeline`,
    which is async. We run it via ``asyncio.run()`` because Celery workers
    are synchronous by default.

    Args:
        repository_id: String UUID of the repository record to process.

    Returns:
        dict with ``repository_id`` and final ``status`` keys.
    """
    logger.info("clone_repository_task started", extra={"repository_id": repository_id})

    repo_uuid = uuid.UUID(repository_id)

    async def _run() -> str:
        """Run the async pipeline and return the final status string."""
        from backend.app.db.session import init_db  # noqa: PLC0415
        from backend.app.services.repository_service import RepositoryService  # noqa: PLC0415

        init_db()

        # Pass session=None — run_clone_pipeline opens its own session
        # context internally and creates a fresh GitHubClient per run.
        service = RepositoryService(session=None)  # type: ignore[arg-type]
        await service.run_clone_pipeline(repo_uuid)
        return "READY"

    try:
        status = asyncio.run(_run())
        logger.info(
            "clone_repository_task completed",
            extra={"repository_id": repository_id, "status": status},
        )
        return {"repository_id": repository_id, "status": status}
    except Exception as exc:
        logger.error(
            "clone_repository_task failed",
            extra={"repository_id": repository_id, "error": str(exc)},
        )
        raise
