"""Celery task definitions for the Code Intelligence Engine.

Task:
    parse_repository_task: Runs the full AST parse pipeline for a
                           single repository identified by UUID.

Follows the same pattern as ``scanner_tasks.py``:
    synchronous Celery task → asyncio.run() → init_db() → async service
"""

import asyncio
import uuid

from celery.utils.log import get_task_logger

from backend.app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name="parser.parse_repository",
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
)
def parse_repository_task(self, repository_id: str) -> dict:
    """Celery task: AST-parse all source files in a repository.

    Delegates all work to
    :meth:`~backend.app.services.parser_service.RepositoryParserService.parse_repository`,
    which is async. We run it via ``asyncio.run()`` because Celery workers
    are synchronous by default.

    Args:
        repository_id: String UUID of the repository record to parse.

    Returns:
        dict with ``repository_id``, ``status``, and aggregate counts.
    """
    logger.info(
        "parse_repository_task started",
        extra={"repository_id": repository_id},
    )

    repo_uuid = uuid.UUID(repository_id)

    async def _run() -> dict:
        """Run the async parse pipeline and return a summary dict.

        Returns:
            dict: Summary with repository_id, status, and counts.
        """
        from backend.app.db.session import init_db, get_session_context  # noqa: PLC0415
        from backend.app.services.parser_service import RepositoryParserService  # noqa: PLC0415

        init_db()

        async with get_session_context() as session:
            service = RepositoryParserService(session=session)
            stats = await service.parse_repository(repo_uuid)

        return {
            "repository_id": repository_id,
            "status": "COMPLETED",
            "total_files": stats.total_files,
            "completed_files": stats.completed_files,
            "failed_files": stats.failed_files,
            "total_symbols": stats.total_symbols,
            "total_functions": stats.total_functions,
            "total_classes": stats.total_classes,
            "total_routes": stats.total_routes,
            "duration_seconds": stats.parse_duration_seconds,
        }

    try:
        result = asyncio.run(_run())
        logger.info(
            "parse_repository_task completed",
            extra={
                "repository_id": repository_id,
                "completed_files": result["completed_files"],
                "total_symbols": result["total_symbols"],
            },
        )
        return result
    except Exception as exc:
        logger.error(
            "parse_repository_task failed",
            extra={"repository_id": repository_id, "error": str(exc)},
        )
        raise
