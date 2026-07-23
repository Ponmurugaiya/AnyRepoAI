"""Celery task definitions for the Symbol Intelligence Engine.

Task:
    index_repository_task: Runs the full symbol-index pipeline for a
                           single repository identified by UUID.

Follows the established pattern used by ``parser_tasks.py`` and
``scanner_tasks.py``:

    Celery task (sync) → asyncio.run() → init_db() → async service
"""

from __future__ import annotations

import asyncio
import uuid

from celery.utils.log import get_task_logger

from backend.app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name="symbol_index.index_repository",
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
)
def index_repository_task(self, repository_id: str) -> dict:
    """Celery task: build the Symbol Index for all source files in a repository.

    Delegates all work to
    :meth:`~backend.app.symbol_index.services.index_service.SymbolIndexService.index_repository`,
    which is async. The synchronous Celery wrapper executes it via
    ``asyncio.run()``.

    Args:
        repository_id: String UUID of the repository record to index.

    Returns:
        dict with ``repository_id``, ``status``, and aggregate symbol counts.
    """
    logger.info(
        "index_repository_task started",
        extra={"repository_id": repository_id},
    )

    repo_uuid = uuid.UUID(repository_id)

    async def _run() -> dict:
        """Run the async indexing pipeline and return a summary dict.

        Returns:
            dict: Summary with repository_id, status, and counts.
        """
        from backend.app.db.session import get_session_context, init_db  # noqa: PLC0415
        from backend.app.symbol_index.services.index_service import SymbolIndexService  # noqa: PLC0415

        init_db()

        async with get_session_context() as session:
            service = SymbolIndexService(session=session)
            stats = await service.index_repository(repo_uuid)

        return {
            "repository_id": repository_id,
            "status": "COMPLETED",
            "total_files": stats.total_files,
            "indexed_files": stats.indexed_files,
            "failed_files": stats.failed_files,
            "total_symbols": stats.total_symbols,
            "duplicate_symbols": stats.duplicate_symbols,
            "duration_seconds": stats.index_duration_seconds,
        }

    try:
        result = asyncio.run(_run())
        logger.info(
            "index_repository_task completed",
            extra={
                "repository_id": repository_id,
                "total_symbols": result["total_symbols"],
                "indexed_files": result["indexed_files"],
            },
        )
        return result
    except Exception as exc:
        logger.error(
            "index_repository_task failed",
            extra={"repository_id": repository_id, "error": str(exc)},
        )
        raise
