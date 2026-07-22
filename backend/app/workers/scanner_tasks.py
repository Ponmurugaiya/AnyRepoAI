"""Celery task definitions for the Repository Scanner module.

Task:
    scan_repository_task: Runs the full file-system scan pipeline for a
                          single repository identified by UUID.

The task is bound (``bind=True``) for access to retry machinery and
uses ``autoretry_for`` with exponential back-off consistent with the
existing ``clone_repository_task`` pattern.
"""

import asyncio
import uuid

from celery import Celery
from celery.utils.log import get_task_logger

from backend.app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name="scanner.scan_repository",
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
)
def scan_repository_task(self, repository_id: str) -> dict:
    """Celery task: scan a repository and persist file metadata.

    Delegates all work to :meth:`RepositoryScannerService.scan_repository`,
    which is async. We run it via ``asyncio.run()`` because Celery workers
    are synchronous by default.

    Args:
        repository_id: String UUID of the repository record to scan.

    Returns:
        dict with ``repository_id``, final ``status``, and scan ``statistics``.
    """
    logger.info(
        "scan_repository_task started",
        extra={"repository_id": repository_id},
    )

    repo_uuid = uuid.UUID(repository_id)

    async def _run() -> dict:
        """Run the async scan pipeline and return a summary dict.

        Returns:
            dict: Summary with repository_id, status, and statistics.
        """
        from backend.app.db.session import init_db  # noqa: PLC0415
        from backend.app.db.session import get_session_context  # noqa: PLC0415
        from backend.app.services.scanner_service import RepositoryScannerService  # noqa: PLC0415

        init_db()

        async with get_session_context() as session:
            service = RepositoryScannerService(session=session)
            stats = await service.scan_repository(repo_uuid)

        return {
            "repository_id": repository_id,
            "status": "COMPLETED",
            "total_files": stats.total_files,
            "scanned_files": stats.scanned_files,
            "ignored_files": stats.ignored_files,
            "failed_files": stats.failed_files,
            "total_bytes": stats.total_bytes,
            "duration_seconds": stats.scan_duration_seconds,
        }

    try:
        result = asyncio.run(_run())
        logger.info(
            "scan_repository_task completed",
            extra={
                "repository_id": repository_id,
                "status": result["status"],
                "scanned_files": result["scanned_files"],
            },
        )
        return result
    except Exception as exc:
        logger.error(
            "scan_repository_task failed",
            extra={"repository_id": repository_id, "error": str(exc)},
        )
        raise
