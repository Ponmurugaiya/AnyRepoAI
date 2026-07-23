"""Celery task definitions for the Knowledge Graph Builder.

Task:
    build_graph_task: Runs the full graph build pipeline for a single
                      repository identified by UUID.

Follows the established pattern used by all other workers in this project:

    Celery task (sync) → asyncio.run() → init_db() → init_neo4j() → async service
"""

from __future__ import annotations

import asyncio
import uuid

from celery.utils.log import get_task_logger

from backend.app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name="graph.build_repository",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def build_graph_task(self, repository_id: str) -> dict:
    """Celery task: build the Knowledge Graph for all code entities in a repository.

    Reads exclusively from the Symbol Index in PostgreSQL; never re-parses
    source files.  Writes all nodes and edges to Neo4j.

    Args:
        repository_id: String UUID of the repository record to build.

    Returns:
        dict with ``repository_id``, ``status``, and aggregate node/edge counts.
    """
    logger.info(
        "build_graph_task started",
        extra={"repository_id": repository_id},
    )

    repo_uuid = uuid.UUID(repository_id)

    async def _run() -> dict:
        """Execute the async graph build pipeline.

        Returns:
            dict: Summary with repository_id, status, node/edge counts.
        """
        from backend.app.db.session import get_session_context, init_db  # noqa: PLC0415
        from backend.app.graph.services.graph_build_service import GraphBuildService  # noqa: PLC0415
        from backend.app.infrastructure.neo4j_client import get_neo4j, init_neo4j  # noqa: PLC0415

        init_db()
        init_neo4j()

        neo4j_driver = get_neo4j()

        async with get_session_context() as pg_session:
            service = GraphBuildService(
                pg_session=pg_session,
                neo4j_driver=neo4j_driver,
            )
            stats = await service.build_graph(repo_uuid)

        return {
            "repository_id": repository_id,
            "status": "COMPLETED" if not stats.error_message else "COMPLETED_WITH_ERRORS",
            "total_nodes": stats.total_nodes,
            "total_edges": stats.total_edges,
            "circular_dependencies": stats.circular_dependency_count,
            "duration_seconds": stats.build_duration_seconds,
            "error": stats.error_message,
        }

    try:
        result = asyncio.run(_run())
        logger.info(
            "build_graph_task completed",
            extra={
                "repository_id": repository_id,
                "total_nodes": result["total_nodes"],
                "total_edges": result["total_edges"],
            },
        )
        return result
    except Exception as exc:
        logger.error(
            "build_graph_task failed",
            extra={"repository_id": repository_id, "error": str(exc)},
        )
        raise
