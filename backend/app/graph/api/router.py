"""Knowledge Graph REST API endpoints.

All graph operations for a repository are scoped under the prefix
``/repositories/{id}/graph``.

Endpoints:

    POST  /repositories/{id}/graph/build
        Enqueue asynchronous graph construction.

    GET   /repositories/{id}/graph/progress
        Current build status and node/edge counts.

    GET   /repositories/{id}/graph/node/{node_id}
        Single node by stable ID.

    GET   /repositories/{id}/graph/node/qname
        Single node by qualified name (query param).

    GET   /repositories/{id}/graph/neighbors/{node_id}
        Connected nodes with their relationships.

    GET   /repositories/{id}/graph/path
        Shortest path between two nodes.

    GET   /repositories/{id}/graph/dependencies
        Full import/dependency subgraph.

    GET   /repositories/{id}/graph/callgraph
        Full call graph.

    GET   /repositories/{id}/graph/analysis/unused-functions
        Functions with no callers.

    GET   /repositories/{id}/graph/analysis/orphan-classes
        Classes with no relationships.

    GET   /repositories/{id}/graph/analysis/circular-dependencies
        Cyclic import/dependency chains.

    GET   /repositories/{id}/graph/analysis/longest-chain
        Longest dependency chain path.

All responses use the unified :class:`~backend.app.schemas.base.APIResponse` envelope.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Query, status

from backend.app.core.exceptions import NotFoundError
from backend.app.core.logging import get_logger
from backend.app.dependencies.database import DBSession
from backend.app.graph.repositories.graph_repository import GraphRepository
from backend.app.graph.schemas.graph import (
    AnalysisResult,
    GraphBuildProgress,
    GraphBuildResponse,
    GraphNeighborResponse,
    GraphNodeResponse,
    GraphPathResponse,
    GraphStatistics,
    GraphSubgraphResponse,
)
from backend.app.graph.services.graph_build_service import GraphBuildService
from backend.app.schemas.base import APIResponse

logger = get_logger(__name__)

router = APIRouter(tags=["Knowledge Graph"])


# ── Helpers ────────────────────────────────────────────────────────────────────


def _get_neo4j_driver():
    """Return the shared Neo4j driver for use in route handlers."""
    from backend.app.infrastructure.neo4j_client import get_neo4j  # noqa: PLC0415
    return get_neo4j()


# ── POST /repositories/{id}/graph/build ───────────────────────────────────────


@router.post(
    "/repositories/{repository_id}/graph/build",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=APIResponse[GraphBuildResponse],
    summary="Start graph construction",
    description=(
        "Enqueues an asynchronous Knowledge Graph build pipeline that reads "
        "from the Symbol Index and writes all nodes and relationships to Neo4j. "
        "Returns immediately with ``status=QUEUED``. "
        "The Symbol Index (POST .../symbols/index) must be completed first."
    ),
    responses={
        202: {"description": "Graph build accepted and enqueued"},
        404: {"description": "Repository not found"},
    },
)
async def build_graph(
    repository_id: uuid.UUID,
    db: DBSession,
    background_tasks: BackgroundTasks,
) -> APIResponse[GraphBuildResponse]:
    """Enqueue Knowledge Graph construction.

    Args:
        repository_id: The UUID path parameter.
        db: Injected SQLAlchemy async session.
        background_tasks: FastAPI background task queue (Celery fallback).

    Returns:
        APIResponse wrapping :class:`GraphBuildResponse`.
    """
    _enqueue_build(repository_id, background_tasks)

    result = GraphBuildResponse(
        repository_id=repository_id,
        status="QUEUED",
        message=(
            "Graph build enqueued. "
            "Poll GET .../graph/progress to track completion."
        ),
    )
    logger.info("Graph build accepted", repository_id=str(repository_id))
    return APIResponse.ok(
        data=result,
        message="Knowledge Graph build has been enqueued.",
    )


# ── GET /repositories/{id}/graph/progress ─────────────────────────────────────


@router.get(
    "/repositories/{repository_id}/graph/progress",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[GraphBuildProgress],
    summary="Get graph build progress",
    description="Returns current node and edge counts for the repository graph.",
    responses={404: {"description": "Repository not found"}},
)
async def get_graph_progress(
    repository_id: uuid.UUID,
    db: DBSession,
) -> APIResponse[GraphBuildProgress]:
    """Return graph build progress.

    Args:
        repository_id: The UUID path parameter.
        db: Injected SQLAlchemy async session.

    Returns:
        APIResponse wrapping :class:`GraphBuildProgress`.
    """
    service = GraphBuildService(
        pg_session=db,
        neo4j_driver=_get_neo4j_driver(),
    )
    progress = await service.get_progress(repository_id)
    return APIResponse.ok(data=progress, message="Graph progress retrieved.")


# ── GET /repositories/{id}/graph/node/{node_id} ───────────────────────────────


@router.get(
    "/repositories/{repository_id}/graph/node/{node_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[GraphNodeResponse],
    summary="Get node by ID",
    description="Returns a single graph node by its stable ID.",
    responses={404: {"description": "Node not found"}},
)
async def get_node(
    repository_id: uuid.UUID,
    node_id: str,
    db: DBSession,
) -> APIResponse[GraphNodeResponse]:
    """Return a single graph node.

    Args:
        repository_id: Repository UUID.
        node_id: Stable node identifier.
        db: Injected SQLAlchemy async session.

    Returns:
        APIResponse wrapping :class:`GraphNodeResponse`.
    """
    graph_repo = GraphRepository(_get_neo4j_driver())
    record = await graph_repo.get_node(str(repository_id), node_id)
    if record is None:
        raise NotFoundError("GraphNode", node_id)
    return APIResponse.ok(
        data=GraphNodeResponse.from_neo4j(record),
        message="Node retrieved.",
    )


# ── GET /repositories/{id}/graph/node/qname ───────────────────────────────────


@router.get(
    "/repositories/{repository_id}/graph/node/by-name",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[GraphNodeResponse],
    summary="Get node by qualified name",
    description="Returns a single graph node by its fully-qualified name.",
    responses={404: {"description": "Node not found"}},
)
async def get_node_by_qualified_name(
    repository_id: uuid.UUID,
    db: DBSession,
    qname: str = Query(description="Fully-qualified symbol name"),
) -> APIResponse[GraphNodeResponse]:
    """Return a node by qualified name.

    Args:
        repository_id: Repository UUID.
        db: Injected SQLAlchemy async session.
        qname: Fully-qualified name query parameter.

    Returns:
        APIResponse wrapping :class:`GraphNodeResponse`.
    """
    graph_repo = GraphRepository(_get_neo4j_driver())
    record = await graph_repo.get_node_by_qualified_name(str(repository_id), qname)
    if record is None:
        raise NotFoundError("GraphNode", qname)
    return APIResponse.ok(
        data=GraphNodeResponse.from_neo4j(record),
        message="Node retrieved.",
    )


# ── GET /repositories/{id}/graph/neighbors/{node_id} ─────────────────────────


@router.get(
    "/repositories/{repository_id}/graph/neighbors/{node_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[list[GraphNeighborResponse]],
    summary="Get node neighbors",
    description=(
        "Returns all nodes directly connected to the specified node, "
        "along with their relationship types."
    ),
)
async def get_neighbors(
    repository_id: uuid.UUID,
    node_id: str,
    db: DBSession,
    direction: str = Query(
        default="both",
        description="Direction: outgoing | incoming | both",
    ),
    edge_types: list[str] | None = Query(
        default=None,
        description="Filter by relationship types (e.g. CALLS, IMPORTS)",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
) -> APIResponse[list[GraphNeighborResponse]]:
    """Return neighbors of a node.

    Args:
        repository_id: Repository UUID.
        node_id: Source node ID.
        db: Injected SQLAlchemy async session.
        direction: Traversal direction.
        edge_types: Optional relationship type filters.
        limit: Maximum neighbors to return.

    Returns:
        APIResponse wrapping list of :class:`GraphNeighborResponse`.
    """
    graph_repo = GraphRepository(_get_neo4j_driver())
    records = await graph_repo.get_neighbors(
        str(repository_id),
        node_id,
        direction=direction,
        edge_types=edge_types,
        limit=limit,
    )
    items = [
        GraphNeighborResponse(
            node=GraphNodeResponse.from_neo4j(r["node"]),
            relationship=r["relationship"],
        )
        for r in records
    ]
    return APIResponse.ok(
        data=items,
        message=f"Retrieved {len(items)} neighbors.",
    )


# ── GET /repositories/{id}/graph/path ─────────────────────────────────────────


@router.get(
    "/repositories/{repository_id}/graph/path",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[GraphPathResponse],
    summary="Find shortest path",
    description="Returns the shortest path between two nodes in the graph.",
)
async def find_path(
    repository_id: uuid.UUID,
    db: DBSession,
    source: str = Query(description="Source node ID"),
    target: str = Query(description="Target node ID"),
    max_depth: int = Query(
        default=10, ge=1, le=30, description="Maximum path length"
    ),
) -> APIResponse[GraphPathResponse]:
    """Return the shortest path between two nodes.

    Args:
        repository_id: Repository UUID.
        db: Injected SQLAlchemy async session.
        source: Source node ID.
        target: Target node ID.
        max_depth: Maximum path length.

    Returns:
        APIResponse wrapping :class:`GraphPathResponse`.
    """
    graph_repo = GraphRepository(_get_neo4j_driver())
    path_nodes = await graph_repo.find_shortest_path(
        str(repository_id), source, target, max_depth=max_depth
    )
    return APIResponse.ok(
        data=GraphPathResponse(
            source_id=source,
            target_id=target,
            path=path_nodes,
            length=max(0, len(path_nodes) - 1),
            found=bool(path_nodes),
        ),
        message="Path query completed.",
    )


# ── GET /repositories/{id}/graph/dependencies ─────────────────────────────────


@router.get(
    "/repositories/{repository_id}/graph/dependencies",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[GraphSubgraphResponse],
    summary="Get dependency graph",
    description=(
        "Returns all IMPORTS and DEPENDS_ON relationships for the repository, "
        "forming the complete dependency subgraph."
    ),
)
async def get_dependency_graph(
    repository_id: uuid.UUID,
    db: DBSession,
) -> APIResponse[GraphSubgraphResponse]:
    """Return the full dependency graph.

    Args:
        repository_id: Repository UUID.
        db: Injected SQLAlchemy async session.

    Returns:
        APIResponse wrapping :class:`GraphSubgraphResponse`.
    """
    graph_repo = GraphRepository(_get_neo4j_driver())
    data = await graph_repo.get_dependency_subgraph(str(repository_id))
    return APIResponse.ok(
        data=GraphSubgraphResponse(
            nodes=data["nodes"],
            edges=data["edges"],
            node_count=len(data["nodes"]),
            edge_count=len(data["edges"]),
        ),
        message="Dependency graph retrieved.",
    )


# ── GET /repositories/{id}/graph/callgraph ────────────────────────────────────


@router.get(
    "/repositories/{repository_id}/graph/callgraph",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[GraphSubgraphResponse],
    summary="Get call graph",
    description="Returns all CALLS relationships for the repository.",
)
async def get_call_graph(
    repository_id: uuid.UUID,
    db: DBSession,
) -> APIResponse[GraphSubgraphResponse]:
    """Return the full call graph.

    Args:
        repository_id: Repository UUID.
        db: Injected SQLAlchemy async session.

    Returns:
        APIResponse wrapping :class:`GraphSubgraphResponse`.
    """
    graph_repo = GraphRepository(_get_neo4j_driver())
    data = await graph_repo.get_call_graph(str(repository_id))
    return APIResponse.ok(
        data=GraphSubgraphResponse(
            nodes=data["nodes"],
            edges=data["edges"],
            node_count=len(data["nodes"]),
            edge_count=len(data["edges"]),
        ),
        message="Call graph retrieved.",
    )


# ── Analysis endpoints ─────────────────────────────────────────────────────────


@router.get(
    "/repositories/{repository_id}/graph/analysis/unused-functions",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AnalysisResult],
    summary="Find unused functions",
    description="Returns functions and methods that have no incoming CALLS edges.",
)
async def find_unused_functions(
    repository_id: uuid.UUID,
    db: DBSession,
    limit: int = Query(default=100, ge=1, le=500),
) -> APIResponse[AnalysisResult]:
    """Return functions with no callers.

    Args:
        repository_id: Repository UUID.
        db: Injected SQLAlchemy async session.
        limit: Maximum results.

    Returns:
        APIResponse wrapping :class:`AnalysisResult`.
    """
    graph_repo = GraphRepository(_get_neo4j_driver())
    nodes = await graph_repo.find_unused_functions(str(repository_id), limit=limit)
    return APIResponse.ok(
        data=AnalysisResult(
            analysis_type="unused_functions",
            repository_id=repository_id,
            items=nodes,
            total=len(nodes),
        ),
        message=f"Found {len(nodes)} unused functions.",
    )


@router.get(
    "/repositories/{repository_id}/graph/analysis/orphan-classes",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AnalysisResult],
    summary="Find orphan classes",
    description="Returns class nodes that have no relationships of any kind.",
)
async def find_orphan_classes(
    repository_id: uuid.UUID,
    db: DBSession,
    limit: int = Query(default=100, ge=1, le=500),
) -> APIResponse[AnalysisResult]:
    """Return classes with no graph connections.

    Args:
        repository_id: Repository UUID.
        db: Injected SQLAlchemy async session.
        limit: Maximum results.

    Returns:
        APIResponse wrapping :class:`AnalysisResult`.
    """
    graph_repo = GraphRepository(_get_neo4j_driver())
    nodes = await graph_repo.find_orphan_classes(str(repository_id), limit=limit)
    return APIResponse.ok(
        data=AnalysisResult(
            analysis_type="orphan_classes",
            repository_id=repository_id,
            items=nodes,
            total=len(nodes),
        ),
        message=f"Found {len(nodes)} orphan classes.",
    )


@router.get(
    "/repositories/{repository_id}/graph/analysis/circular-dependencies",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AnalysisResult],
    summary="Find circular dependencies",
    description="Returns cyclic import or dependency chains.",
)
async def find_circular_dependencies(
    repository_id: uuid.UUID,
    db: DBSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> APIResponse[AnalysisResult]:
    """Return cyclic import chains.

    Args:
        repository_id: Repository UUID.
        db: Injected SQLAlchemy async session.
        limit: Maximum cycles to return.

    Returns:
        APIResponse wrapping :class:`AnalysisResult`.
    """
    graph_repo = GraphRepository(_get_neo4j_driver())
    cycles = await graph_repo.find_circular_dependencies(
        str(repository_id), limit=limit
    )
    return APIResponse.ok(
        data=AnalysisResult(
            analysis_type="circular_dependencies",
            repository_id=repository_id,
            items=cycles,
            total=len(cycles),
        ),
        message=f"Found {len(cycles)} circular dependency chains.",
    )


@router.get(
    "/repositories/{repository_id}/graph/analysis/longest-chain",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[AnalysisResult],
    summary="Find longest dependency chain",
    description="Returns the qualified-name sequence of the longest import/dependency chain.",
)
async def find_longest_chain(
    repository_id: uuid.UUID,
    db: DBSession,
) -> APIResponse[AnalysisResult]:
    """Return the longest dependency chain.

    Args:
        repository_id: Repository UUID.
        db: Injected SQLAlchemy async session.

    Returns:
        APIResponse wrapping :class:`AnalysisResult`.
    """
    graph_repo = GraphRepository(_get_neo4j_driver())
    chain = await graph_repo.find_longest_dependency_chain(str(repository_id))
    return APIResponse.ok(
        data=AnalysisResult(
            analysis_type="longest_dependency_chain",
            repository_id=repository_id,
            items=chain,
            total=len(chain),
        ),
        message=f"Longest chain has {max(0, len(chain) - 1)} hops.",
    )


# ── Enqueue helpers ────────────────────────────────────────────────────────────


def _enqueue_build(
    repository_id: uuid.UUID,
    background_tasks: BackgroundTasks,
) -> None:
    """Dispatch graph build to Celery, or fall back to BackgroundTasks.

    Args:
        repository_id: UUID of the repository to build.
        background_tasks: FastAPI background task queue (fallback path).
    """
    try:
        from backend.app.graph.workers.graph_tasks import build_graph_task  # noqa: PLC0415

        build_graph_task.delay(str(repository_id))
        logger.info(
            "Graph build task dispatched to Celery",
            repository_id=str(repository_id),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Celery unavailable; falling back to FastAPI BackgroundTasks",
            repository_id=str(repository_id),
            error=str(exc),
        )
        background_tasks.add_task(_run_build_in_background, repository_id)


async def _run_build_in_background(repository_id: uuid.UUID) -> None:
    """BackgroundTasks fallback: run the graph build pipeline in-process.

    Args:
        repository_id: UUID of the repository to build.
    """
    from backend.app.db.session import get_session_context  # noqa: PLC0415
    from backend.app.infrastructure.neo4j_client import get_neo4j  # noqa: PLC0415

    async with get_session_context() as pg_session:
        service = GraphBuildService(
            pg_session=pg_session,
            neo4j_driver=get_neo4j(),
        )
        try:
            await service.build_graph(repository_id)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "BackgroundTask graph build raised",
                repository_id=str(repository_id),
                error=str(exc),
            )
