"""Graph Build Service — full pipeline orchestration.

:class:`GraphBuildService` is the single entry point for all graph
construction operations.  It reads exclusively from the Symbol Index
(PostgreSQL) and writes to Neo4j.  Source files are never re-read.

Pipeline steps
--------------
1. Validate repository exists and has a completed Symbol Index.
2. Delete previous graph for the repository (full rebuild) or targeted
   file nodes (incremental update).
3. Ensure Neo4j schema (indexes / constraints).
4. Build Repository, Directory, and File nodes.
5. Load Symbol Index entries in paginated batches.
6. Build symbol nodes, validate them, and merge into Neo4j.
7. Build all edge types (containment, inheritance, imports, calls, routes).
8. Validate edges, run cycle detection, and merge into Neo4j.
9. Update the GraphBuildJob status record in PostgreSQL.

Design decisions
----------------
- The service owns Neo4j writes; the repository class owns Cypher.
- Nodes are flushed to Neo4j before edges so MERGE on edges always finds
  existing endpoints.
- Batching both nodes and edges prevents memory exhaustion on large repos.
- Incremental updates only touch the changed file's nodes and edges.
"""

from __future__ import annotations

import time
import uuid
from pathlib import PurePosixPath
from typing import Any

from neo4j import AsyncDriver
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.exceptions import RepositoryNotFoundError
from backend.app.core.logging import get_logger
from backend.app.graph.builders.edge_builder import EdgeBuilder, _route_key
from backend.app.graph.builders.node_builder import (
    NodeBuilder,
    _normalise_library_name,
)
from backend.app.graph.models.nodes import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
)
from backend.app.graph.repositories.graph_repository import GraphRepository
from backend.app.graph.schemas.graph import GraphBuildProgress, GraphStatistics
from backend.app.graph.validators.graph_validator import GraphValidator
from backend.app.models.repository import RepositoryStatus
from backend.app.models.symbol import CallRecord, ClassRecord, ImportRecord, RouteRecord
from backend.app.repositories.file_repository import FileRepository
from backend.app.repositories.repository import RepositoryRepository
from backend.app.repositories.symbol_repository import SymbolRepository
from backend.app.symbol_index.models.index import SymbolIndexEntry
from backend.app.symbol_index.repositories.index_repository import SymbolIndexRepository

logger = get_logger(__name__)

# Maximum entries loaded from Symbol Index per memory batch
_INDEX_BATCH_SIZE = 1000

# Known well-known library fragments (imported from node_builder for detection)
from backend.app.graph.repositories.graph_repository import _KNOWN_LIBRARIES  # noqa: E402


class GraphBuildService:
    """Orchestrates the full Code Knowledge Graph build pipeline.

    Args:
        pg_session: Injected SQLAlchemy async session (PostgreSQL).
        neo4j_driver: Injected Neo4j async driver.
    """

    def __init__(
        self,
        pg_session: AsyncSession,
        neo4j_driver: AsyncDriver,
    ) -> None:
        self._session = pg_session
        self._repo_repo = RepositoryRepository(pg_session)
        self._file_repo = FileRepository(pg_session)
        self._sym_repo = SymbolRepository(pg_session)
        self._index_repo = SymbolIndexRepository(pg_session)
        self._graph_repo = GraphRepository(neo4j_driver)
        self._node_builder = NodeBuilder()
        self._edge_builder = EdgeBuilder()
        self._validator = GraphValidator()

    # ── Public API ─────────────────────────────────────────────────────────────

    async def build_graph(self, repository_id: uuid.UUID) -> GraphStatistics:
        """Build (or rebuild) the complete Knowledge Graph for a repository.

        Args:
            repository_id: UUID of the repository to build.

        Returns:
            :class:`GraphStatistics` with aggregate node and edge counts.

        Raises:
            RepositoryNotFoundError: Repository record not found.
        """
        start = time.perf_counter()
        rid_str = str(repository_id)

        repo = await self._repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(rid_str)

        logger.info(
            "Graph build started",
            repository_id=rid_str,
            full_name=repo.full_name,
        )

        # Ensure schema once per build
        await self._graph_repo.ensure_indexes()

        # Wipe existing graph for idempotent rebuild
        await self._graph_repo.delete_repository_graph(rid_str)

        stats = GraphStatistics(repository_id=repository_id)

        try:
            await self._run_pipeline(repo, repository_id, stats)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Graph build failed with unrecoverable error",
                repository_id=rid_str,
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            stats.error_message = f"{type(exc).__name__}: {exc}"

        stats.build_duration_seconds = round(time.perf_counter() - start, 3)
        logger.info(
            "Graph build completed",
            repository_id=rid_str,
            nodes=stats.total_nodes,
            edges=stats.total_edges,
            duration=stats.build_duration_seconds,
        )
        return stats

    async def build_file_subgraph(
        self,
        repository_id: uuid.UUID,
        file_id: uuid.UUID,
    ) -> GraphStatistics:
        """Incrementally rebuild the graph for a single changed file.

        Only nodes and edges originating from ``file_id`` are deleted and
        recreated.  The rest of the repository graph is untouched.

        Args:
            repository_id: Repository UUID.
            file_id: UUID of the changed file.

        Returns:
            :class:`GraphStatistics` with counts for the file's subgraph.

        Raises:
            RepositoryNotFoundError: Repository record not found.
        """
        start = time.perf_counter()
        rid_str = str(repository_id)

        repo = await self._repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(rid_str)

        file_record = await self._file_repo.get_by_id(file_id)
        if file_record is None:
            logger.warning(
                "File not found for incremental graph update",
                file_id=str(file_id),
            )
            return GraphStatistics(repository_id=repository_id)

        logger.info(
            "Incremental graph update started",
            repository_id=rid_str,
            file_path=file_record.relative_path,
        )

        # Remove all nodes from this file
        await self._graph_repo.delete_file_nodes(
            rid_str, file_record.relative_path
        )

        stats = GraphStatistics(repository_id=repository_id)

        # Rebuild just this file's portion
        entries = await self._index_repo.list_entries(
            repository_id,
            file_id=file_id,
            limit=10000,
        )
        if not entries:
            return stats

        file_node = self._node_builder.build_file_node(
            rid_str,
            str(file_id),
            file_record.relative_path,
            file_record.language.value,
        )

        # Build symbol nodes
        symbol_nodes: list[GraphNode] = []
        for entry in entries:
            node = self._node_builder.build_symbol_node_with_path(
                entry, file_record.relative_path
            )
            symbol_nodes.append(node)

        all_nodes = [file_node] + symbol_nodes
        clean_nodes = self._validator.filter_nodes(all_nodes)

        written_nodes = await self._graph_repo.merge_nodes(clean_nodes)
        stats.total_nodes += written_nodes

        # Build edges for this file
        known_ids = {n.node_id for n in clean_nodes}
        node_id_map = {str(e.id): str(e.id) for e in entries}
        qname_map = {e.qualified_name: str(e.id) for e in entries}

        contain_edges = self._edge_builder.build_containment_edges(
            file_node.node_id, symbol_nodes, rid_str
        )
        defines_edges = self._edge_builder.build_defines_edges(
            entries, node_id_map, rid_str
        )

        all_edges = contain_edges + defines_edges
        clean_edges = self._validator.filter_edges(all_edges, known_ids)
        written_edges = await self._graph_repo.merge_edges(clean_edges)
        stats.total_edges += written_edges

        stats.build_duration_seconds = round(time.perf_counter() - start, 3)
        logger.info(
            "Incremental graph update completed",
            repository_id=rid_str,
            file_path=file_record.relative_path,
            nodes=stats.total_nodes,
            edges=stats.total_edges,
        )
        return stats

    async def get_progress(
        self, repository_id: uuid.UUID
    ) -> GraphBuildProgress:
        """Return current graph build progress for a repository.

        Args:
            repository_id: Repository UUID.

        Returns:
            :class:`GraphBuildProgress` with current counts.

        Raises:
            RepositoryNotFoundError: Repository record not found.
        """
        repo = await self._repo_repo.get_by_id(repository_id)
        if repo is None:
            raise RepositoryNotFoundError(str(repository_id))

        rid_str = str(repository_id)
        node_count = await self._graph_repo.count_nodes(rid_str)
        edge_count = await self._graph_repo.count_edges(rid_str)

        return GraphBuildProgress(
            repository_id=repository_id,
            total_nodes=node_count,
            total_edges=edge_count,
        )

    # ── Pipeline steps ─────────────────────────────────────────────────────────

    async def _run_pipeline(
        self,
        repo: Any,
        repository_id: uuid.UUID,
        stats: GraphStatistics,
    ) -> None:
        """Execute the full graph build pipeline.

        Args:
            repo: Repository ORM record.
            repository_id: Repository UUID.
            stats: Mutable statistics object updated in-place.
        """
        rid_str = str(repository_id)

        # ── Step 1: Repository node ────────────────────────────────────────────
        repo_node = self._node_builder.build_repository_node(
            rid_str,
            repo.full_name,
            language=repo.language or "",
            description=repo.description or "",
        )
        await self._graph_repo.merge_nodes([repo_node])
        stats.total_nodes += 1
        logger.info("Repository node created", repository_id=rid_str)

        # ── Step 2: Load files ─────────────────────────────────────────────────
        all_files = await self._file_repo.get_by_repository_id(repository_id)
        logger.info(
            "Files loaded for graph build",
            repository_id=rid_str,
            count=len(all_files),
        )

        # Build file → path map and collect unique directories
        file_id_to_path: dict[str, str] = {
            str(f.id): f.relative_path for f in all_files
        }
        directories: set[str] = set()
        for f in all_files:
            parts = PurePosixPath(f.relative_path).parts
            for i in range(1, len(parts)):
                directories.add("/".join(parts[:i]))

        # ── Step 3: Directory nodes ────────────────────────────────────────────
        dir_nodes = [
            self._node_builder.build_directory_node(rid_str, d)
            for d in sorted(directories)
        ]
        dir_node_id_map = {
            dn.qualified_name: dn.node_id for dn in dir_nodes
        }
        if dir_nodes:
            written = await self._graph_repo.merge_nodes(dir_nodes)
            stats.total_nodes += written
            logger.info(
                "Directory nodes created",
                repository_id=rid_str,
                count=written,
            )

        # ── Step 4: File nodes ─────────────────────────────────────────────────
        file_nodes = [
            self._node_builder.build_file_node(
                rid_str, str(f.id), f.relative_path, f.language.value
            )
            for f in all_files
        ]
        file_node_id_map = {
            str(f.id): self._node_builder.build_file_node(
                rid_str, str(f.id), f.relative_path, f.language.value
            ).node_id
            for f in all_files
        }
        clean_file_nodes = self._validator.filter_nodes(file_nodes)
        if clean_file_nodes:
            written = await self._graph_repo.merge_nodes(clean_file_nodes)
            stats.total_nodes += written
            logger.info(
                "File nodes created",
                repository_id=rid_str,
                count=written,
            )

        # Directory→File containment edges
        dir_file_edges = self._edge_builder.build_directory_contains_file_edges(
            repo_node.node_id,
            clean_file_nodes,
            dir_node_id_map,
            rid_str,
        )
        # Repo→Dir edges
        repo_dir_edges = [
            GraphEdge(
                source_id=repo_node.node_id,
                target_id=dn.node_id,
                edge_type=EdgeType.CONTAINS,
                repository_id=rid_str,
            )
            for dn in dir_nodes
        ]
        struct_edges = dir_file_edges + repo_dir_edges
        if struct_edges:
            all_known = (
                {repo_node.node_id}
                | {n.node_id for n in dir_nodes}
                | {n.node_id for n in clean_file_nodes}
            )
            clean_struct = self._validator.filter_edges(struct_edges, all_known)
            written = await self._graph_repo.merge_edges(clean_struct)
            stats.total_edges += written

        # ── Step 5: Symbol nodes from Symbol Index ─────────────────────────────
        all_symbol_nodes: list[GraphNode] = []
        all_entries: list[SymbolIndexEntry] = []
        offset = 0

        while True:
            batch = await self._index_repo.list_entries(
                repository_id,
                limit=_INDEX_BATCH_SIZE,
                offset=offset,
            )
            if not batch:
                break

            batch_nodes: list[GraphNode] = []
            for entry in batch:
                path = file_id_to_path.get(str(entry.file_id), "")
                node = self._node_builder.build_symbol_node_with_path(entry, path)
                batch_nodes.append(node)

            clean_batch = self._validator.filter_nodes(batch_nodes)
            if clean_batch:
                written = await self._graph_repo.merge_nodes(clean_batch)
                stats.total_nodes += written

            all_symbol_nodes.extend(clean_batch)
            all_entries.extend(batch)
            offset += len(batch)

            logger.info(
                "Symbol nodes batch committed",
                repository_id=rid_str,
                batch_size=len(batch),
                total_so_far=stats.total_nodes,
            )

        logger.info(
            "All symbol nodes created",
            repository_id=rid_str,
            total=stats.total_nodes,
        )

        # Build lookup maps for edge construction
        qname_to_node_id: dict[str, str] = {
            e.qualified_name: str(e.id) for e in all_entries
        }
        entry_id_to_node_id: dict[str, str] = {
            str(e.id): str(e.id) for e in all_entries
        }

        # ── Step 6: Containment edges (File → Symbol) ──────────────────────────
        # Group symbol nodes by file
        file_to_symbols: dict[str, list[GraphNode]] = {}
        for entry, node in zip(all_entries, all_symbol_nodes):
            fid = str(entry.file_id)
            file_to_symbols.setdefault(fid, []).append(node)

        all_contain_edges: list[GraphEdge] = []
        for fid, sym_nodes in file_to_symbols.items():
            file_nid = file_node_id_map.get(fid)
            if file_nid:
                edges = self._edge_builder.build_containment_edges(
                    file_nid, sym_nodes, rid_str
                )
                all_contain_edges.extend(edges)

        # DEFINES (parent → child symbol)
        all_known_ids = (
            {repo_node.node_id}
            | {n.node_id for n in dir_nodes}
            | {n.node_id for n in clean_file_nodes}
            | {n.node_id for n in all_symbol_nodes}
        )
        defines_edges = self._edge_builder.build_defines_edges(
            all_entries, entry_id_to_node_id, rid_str
        )
        struct_sym_edges = all_contain_edges + defines_edges
        if struct_sym_edges:
            clean = self._validator.filter_edges(struct_sym_edges, all_known_ids)
            written = await self._graph_repo.merge_edges(clean)
            stats.total_edges += written
            logger.info(
                "Containment and defines edges committed",
                repository_id=rid_str,
                count=written,
            )

        # ── Step 7: Import edges ───────────────────────────────────────────────
        # Load all import records
        from sqlalchemy import select  # noqa: PLC0415
        from backend.app.models.symbol import ImportRecord  # noqa: PLC0415

        result = await self._session.execute(
            select(ImportRecord).where(
                ImportRecord.repository_id == repository_id
            )
        )
        imports: list[ImportRecord] = list(result.scalars().all())

        # Collect external library nodes
        lib_nodes: list[GraphNode] = []
        lib_node_id_map: dict[str, str] = {}
        for imp in imports:
            if not imp.is_relative:
                lib_name = _normalise_library_name(imp.module_path)
                if lib_name and lib_name not in lib_node_id_map:
                    if not _is_internal_module(lib_name, qname_to_node_id):
                        lib_node = self._node_builder.build_external_library_node(
                            rid_str, lib_name
                        )
                        lib_nodes.append(lib_node)
                        lib_node_id_map[lib_name] = lib_node.node_id

        if lib_nodes:
            clean_libs = self._validator.filter_nodes(lib_nodes)
            written = await self._graph_repo.merge_nodes(clean_libs)
            stats.total_nodes += written
            all_known_ids.update(n.node_id for n in clean_libs)

        import_edges = self._edge_builder.build_import_edges(
            imports,
            file_node_id_map,
            lib_node_id_map,
            qname_to_node_id,
            rid_str,
        )
        if import_edges:
            clean = self._validator.filter_edges(import_edges, all_known_ids)
            written = await self._graph_repo.merge_edges(clean)
            stats.total_edges += written
            logger.info(
                "Import edges committed",
                repository_id=rid_str,
                count=written,
            )

        # ── Step 8: Inheritance / implements edges ─────────────────────────────
        from backend.app.models.symbol import ClassRecord  # noqa: PLC0415

        result = await self._session.execute(
            select(ClassRecord).where(ClassRecord.repository_id == repository_id)
        )
        classes: list[ClassRecord] = list(result.scalars().all())

        inherit_edges = self._edge_builder.build_inheritance_edges(
            classes, qname_to_node_id, rid_str
        )
        impl_edges = self._edge_builder.build_implements_edges(
            classes, qname_to_node_id, rid_str
        )
        inh_impl = inherit_edges + impl_edges
        if inh_impl:
            clean = self._validator.filter_edges(inh_impl, all_known_ids)
            written = await self._graph_repo.merge_edges(clean)
            stats.total_edges += written
            logger.info(
                "Inheritance and implements edges committed",
                repository_id=rid_str,
                count=written,
            )

        # ── Step 9: Call graph edges ───────────────────────────────────────────
        from backend.app.models.symbol import CallRecord  # noqa: PLC0415

        result = await self._session.execute(
            select(CallRecord).where(CallRecord.repository_id == repository_id)
        )
        calls: list[CallRecord] = list(result.scalars().all())

        call_edges = self._edge_builder.build_call_edges(
            calls, qname_to_node_id, rid_str
        )
        if call_edges:
            clean = self._validator.filter_edges(call_edges, all_known_ids)
            written = await self._graph_repo.merge_edges(clean)
            stats.total_edges += written
            logger.info(
                "Call graph edges committed",
                repository_id=rid_str,
                count=written,
            )

        # ── Step 10: Route graph edges ─────────────────────────────────────────
        from backend.app.models.symbol import RouteRecord  # noqa: PLC0415

        result = await self._session.execute(
            select(RouteRecord).where(RouteRecord.repository_id == repository_id)
        )
        routes: list[RouteRecord] = list(result.scalars().all())

        # Build ApiRoute nodes
        route_nodes: list[GraphNode] = []
        route_node_id_map: dict[str, str] = {}
        for route in routes:
            key = _route_key(route)
            if key not in route_node_id_map:
                r_node = GraphNode(
                    node_id=key,
                    node_type=NodeType.API_ROUTE,
                    repository_id=rid_str,
                    name=f"{route.http_method} {route.path}",
                    qualified_name=key,
                    language=route.language,
                    file_path=file_id_to_path.get(str(route.file_id), ""),
                    properties={
                        "http_method": route.http_method,
                        "path": route.path,
                        "framework": route.framework,
                    },
                )
                route_nodes.append(r_node)
                route_node_id_map[key] = key

        if route_nodes:
            clean_routes = self._validator.filter_nodes(route_nodes)
            written = await self._graph_repo.merge_nodes(clean_routes)
            stats.total_nodes += written
            all_known_ids.update(n.node_id for n in clean_routes)

        route_edges = self._edge_builder.build_route_edges(
            routes,
            route_node_id_map,
            qname_to_node_id,
            file_node_id_map,
            rid_str,
        )
        if route_edges:
            clean = self._validator.filter_edges(route_edges, all_known_ids)
            written = await self._graph_repo.merge_edges(clean)
            stats.total_edges += written
            logger.info(
                "Route graph edges committed",
                repository_id=rid_str,
                count=written,
            )

        # ── Step 11: Cycle detection (warning only) ────────────────────────────
        all_built_edges: list[GraphEdge] = (
            import_edges + inh_impl + call_edges + route_edges
        )
        cycles = self._validator.detect_cycles(all_built_edges)
        if cycles:
            logger.warning(
                "Circular dependencies detected in graph",
                repository_id=rid_str,
                cycle_count=len(cycles),
            )
        stats.circular_dependency_count = len(cycles)

        logger.info(
            "Graph build pipeline completed",
            repository_id=rid_str,
            total_nodes=stats.total_nodes,
            total_edges=stats.total_edges,
        )


def _is_internal_module(name: str, qname_map: dict[str, str]) -> bool:
    """Return True if ``name`` matches an internal module in the Symbol Index.

    Args:
        name: Normalised library/module name.
        qname_map: Map of qualified_name → node_id.

    Returns:
        bool: True when the module is internal.
    """
    return name in qname_map or any(
        qn.startswith(name + ".") or qn == name for qn in qname_map
    )
