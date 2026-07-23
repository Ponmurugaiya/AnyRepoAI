"""Symbol Index Celery workers package."""

from backend.app.symbol_index.workers.index_tasks import index_repository_task

__all__ = ["index_repository_task"]
