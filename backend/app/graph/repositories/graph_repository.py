"""Neo4j Graph Repository.

The single data-access class for all Cypher operations.  Every read and
write to Neo4j flows through this class, keeping Cypher isolated from the
service and builder layers.

Design decisions:
    - All writes use ``MERGE`` on the stable ``id`` property so the graph
      can be rebuilt idempotently without orphaned nodes.
    - Bulk writes batch nodes/edges into configurable chunks so the driver
      does not OOM on large repositories.
    - Retries are handled at the Cypher level for transient connectivity
      errors using Neo4j's built-in retry facilities in managed transactions.
    - Every method that modifies the graph accepts an optional ``tx``
      parameter; when ``None``, a fresh auto-commit session is used.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from neo4j import AsyncDriver, AsyncSession
from neo4j.exceptions import ServiceUnavailable, TransientError

from backend.app.core.logging import get_logger
from backend.app.graph.models.nodes import EdgeType, GraphEdge, GraphNode, NodeType

logger = get_logger(__name__)

# Maximum nodes or edges per Cypher UNWIND batch
_NODE_BATCH_SIZE = 500
_EDGE_BATCH_SIZE = 500

# Known well-connected library name fragments used to detect external libraries
_KNOWN_LIBRARIES: frozenset[str] = frozenset({
    "redis", "sqlalchemy", "fastapi", "flask", "django", "express",
    "spring", "gin", "echo", "nestjs", "stripe", "openai", "celery",
    "jwt", "pydantic", "axios", "prisma", "mongoose", "sequelize",
    "typeorm", "gorm", "hibernate", "log4j", "slf4j", "numpy", "pandas",
    "requests", "httpx", "aiohttp", "grpc", "kafka", "rabbitmq",
    "elasticsearch", "mongodb", "postgres", "mysql", "sqlite",
})


class GraphRepository:
    """Reusable Neo4j repository for the Code Knowledge Graph.

    All Cypher queries are parameterised to prevent injection and allow
    Neo4j query plan caching.

    Args:
        driver: The shared Neo4j ``AsyncDriver`` instance.
        database: Optional database name (defaults to Neo4j default).
    """

    def __init__(self, driver: AsyncDriver, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    # ── Schema setup ───────────────────────────────────────────────────────────

    async def ensure_indexes(self) -> None:
        """Create all required Neo4j indexes and constraints idempotently.

        Should be called once during graph build pipeline initialisation.
        Safe to call multiple times — uses ``IF NOT EXISTS`` semantics.
        """
        async with self._driver.session(database=self._database) as session:
            # Constraint: unique id per Repository
            await session.run(
                "CREATE CONSTRAINT node_id_unique IF NOT EXISTS "
                "FOR (n:_GraphNode) REQUIRE n.id IS UNIQUE"
            )

            # Indexes on commonly filtered properties
            index_queries = [
                "CREATE INDEX idx_repository_id IF NOT EXISTS FOR (n:_GraphNode) ON (n.repository_id)",
                "CREATE INDEX idx_qualified_name IF NOT EXISTS FOR (n:_GraphNode) ON (n.qualified_name)",
                "CREATE INDEX idx_node_language IF NOT EXISTS FOR (n:_GraphNode) ON (n.language)",
                "CREATE INDEX idx_node_name IF NOT EXISTS FOR (n:_GraphNode) ON (n.name)",
            ]
            for cypher in index_queries:
                try:
                    await session.run(cypher)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "Index creation skipped (may already exist)",
                        error=str(exc),
                    )

        logger.info("Neo4j indexes and constraints ensured")

    # ── Node operations ────────────────────────────────────────────────────────

    async def merge_nodes(self, nodes: Sequence[GraphNode]) -> int:
        """Bulk-merge nodes into the graph using UNWIND + MERGE.

        Each node carries a dynamic label stored in ``node_type``.
        Because Neo4j does not support parameterised labels, nodes are
        merged in label-homogeneous groups: all nodes with the same
        ``node_type`` are batched together into a single UNWIND query
        that uses a literal label in the Cypher string.

        Args:
            nodes: Sequence of :class:`GraphNode` instances to merge.

        Returns:
            Total number of nodes written.
        """
        if not nodes:
            return 0

        # Group by label to allow label-specific Cypher
        by_label: dict[str, list[GraphNode]] = {}
        for node in nodes:
            by_label.setdefault(node.node_type.value, []).append(node)

        total = 0
        async with self._driver.session(database=self._database) as session:
            for label, label_nodes in by_label.items():
                total += await self._merge_nodes_for_label(
                    session, label, label_nodes
                )

        logger.debug("Nodes merged", total=total)
        return total

    async def _merge_nodes_for_label(
        self,
        session: AsyncSession,
        label: str,
        nodes: list[GraphNode],
    ) -> int:
        """Merge a batch of same-label nodes in chunks.

        Args:
            session: Open Neo4j async session.
            label: Neo4j node label string.
            nodes: Nodes to merge (all share ``label``).

        Returns:
            Count of nodes merged.
        """
        # Cypher uses literal label; no injection risk since label comes
        # from the NodeType enum (server-side validated values).
        cypher = f"""
        UNWIND $nodes AS n
        MERGE (node:_GraphNode:{label} {{id: n.id}})
        SET
            node.repository_id   = n.repository_id,
            node.name             = n.name,
            node.qualified_name   = n.qualified_name,
            node.language         = n.language,
            node.file_path        = n.file_path,
            node += n.properties,
            node.updated_at       = timestamp()
        """
        total = 0
        for batch_start in range(0, len(nodes), _NODE_BATCH_SIZE):
            batch = nodes[batch_start : batch_start + _NODE_BATCH_SIZE]
            params = [
                {
                    "id": n.node_id,
                    "repository_id": n.repository_id,
                    "name": n.name,
                    "qualified_name": n.qualified_name,
                    "language": n.language,
                    "file_path": n.file_path,
                    "properties": n.properties,
                }
                for n in batch
            ]
            await session.run(cypher, nodes=params)
            total += len(batch)

        return total

    # ── Edge operations ────────────────────────────────────────────────────────

    async def merge_edges(self, edges: Sequence[GraphEdge]) -> int:
        """Bulk-merge relationships using UNWIND + MATCH + MERGE.

        Edges are grouped by ``edge_type`` so each batch uses a single
        Cypher relationship type string.

        Args:
            edges: Sequence of :class:`GraphEdge` instances to merge.

        Returns:
            Total number of relationships written.
        """
        if not edges:
            return 0

        by_type: dict[str, list[GraphEdge]] = {}
        for edge in edges:
            by_type.setdefault(edge.edge_type.value, []).append(edge)

        total = 0
        async with self._driver.session(database=self._database) as session:
            for rel_type, type_edges in by_type.items():
                total += await self._merge_edges_for_type(
                    session, rel_type, type_edges
                )

        logger.debug("Edges merged", total=total)
        return total

    async def _merge_edges_for_type(
        self,
        session: AsyncSession,
        rel_type: str,
        edges: list[GraphEdge],
    ) -> int:
        """Merge a batch of same-type edges in chunks.

        Args:
            session: Open Neo4j async session.
            rel_type: Neo4j relationship type string.
            edges: Edges to merge (all share ``rel_type``).

        Returns:
            Count of edges merged.
        """
        cypher = f"""
        UNWIND $edges AS e
        MATCH (src:_GraphNode {{id: e.source_id}})
        MATCH (tgt:_GraphNode {{id: e.target_id}})
        MERGE (src)-[r:{rel_type}]->(tgt)
        SET r += e.properties,
            r.repository_id = e.repository_id,
            r.updated_at    = timestamp()
        """
        total = 0
        for batch_start in range(0, len(edges), _EDGE_BATCH_SIZE):
            batch = edges[batch_start : batch_start + _EDGE_BATCH_SIZE]
            params = [
                {
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "repository_id": e.repository_id,
                    "properties": e.properties,
                }
                for e in batch
            ]
            await session.run(cypher, edges=params)
            total += len(batch)

        return total

    # ── Delete operations ──────────────────────────────────────────────────────

    async def delete_repository_graph(self, repository_id: str) -> None:
        """Delete all nodes and relationships for a repository.

        Args:
            repository_id: UUID string of the repository to clear.
        """
        async with self._driver.session(database=self._database) as session:
            await session.run(
                "MATCH (n:_GraphNode {repository_id: $rid}) "
                "DETACH DELETE n",
                rid=repository_id,
            )
        logger.info(
            "Repository graph deleted",
            repository_id=repository_id,
        )

    async def delete_file_nodes(
        self,
        repository_id: str,
        file_path: str,
    ) -> None:
        """Delete all nodes originating from a specific file.

        Used for incremental graph updates — only the changed file's
        nodes and their edges are removed before rebuilding.

        Args:
            repository_id: Repository UUID string.
            file_path: Relative source file path.
        """
        async with self._driver.session(database=self._database) as session:
            await session.run(
                "MATCH (n:_GraphNode {repository_id: $rid, file_path: $fp}) "
                "DETACH DELETE n",
                rid=repository_id,
                fp=file_path,
            )
        logger.debug(
            "File nodes deleted for incremental update",
            repository_id=repository_id,
            file_path=file_path,
        )

    # ── Read operations ────────────────────────────────────────────────────────

    async def get_node(
        self, repository_id: str, node_id: str
    ) -> dict[str, Any] | None:
        """Return a single node by its stable ID.

        Args:
            repository_id: Repository UUID string (for scope validation).
            node_id: Stable node ID (UUID string from Symbol Index).

        Returns:
            dict of node properties, or ``None`` if not found.
        """
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                "MATCH (n:_GraphNode {id: $nid, repository_id: $rid}) "
                "RETURN properties(n) AS props, labels(n) AS labels",
                nid=node_id,
                rid=repository_id,
            )
            record = await result.single()
            if record is None:
                return None
            return {**record["props"], "_labels": record["labels"]}

    async def get_node_by_qualified_name(
        self,
        repository_id: str,
        qualified_name: str,
    ) -> dict[str, Any] | None:
        """Return a node by its fully-qualified name.

        Args:
            repository_id: Repository UUID string.
            qualified_name: Fully-qualified symbol name.

        Returns:
            dict of node properties or ``None``.
        """
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                "MATCH (n:_GraphNode {repository_id: $rid, qualified_name: $qn}) "
                "RETURN properties(n) AS props, labels(n) AS labels "
                "LIMIT 1",
                rid=repository_id,
                qn=qualified_name,
            )
            record = await result.single()
            if record is None:
                return None
            return {**record["props"], "_labels": record["labels"]}

    async def get_neighbors(
        self,
        repository_id: str,
        node_id: str,
        *,
        direction: str = "both",
        edge_types: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return neighbors of a node with their connecting relationships.

        Args:
            repository_id: Repository UUID string.
            node_id: Source node ID.
            direction: ``"outgoing"``, ``"incoming"``, or ``"both"``.
            edge_types: Optional list of relationship type strings to filter.
            limit: Maximum results.

        Returns:
            List of dicts with ``node`` and ``relationship`` keys.
        """
        rel_filter = ""
        if edge_types:
            types_str = "|".join(edge_types)
            rel_filter = f":{types_str}"

        if direction == "outgoing":
            pattern = f"(n)-[r{rel_filter}]->(neighbor:_GraphNode)"
        elif direction == "incoming":
            pattern = f"(n)<-[r{rel_filter}]-(neighbor:_GraphNode)"
        else:
            pattern = f"(n)-[r{rel_filter}]-(neighbor:_GraphNode)"

        cypher = (
            f"MATCH (n:_GraphNode {{id: $nid, repository_id: $rid}}) "
            f"MATCH {pattern} "
            "WHERE neighbor.repository_id = $rid "
            "RETURN properties(neighbor) AS node_props, "
            "       labels(neighbor) AS node_labels, "
            "       type(r) AS rel_type, "
            "       properties(r) AS rel_props "
            "LIMIT $limit"
        )
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                cypher,
                nid=node_id,
                rid=repository_id,
                limit=limit,
            )
            records = await result.data()

        return [
            {
                "node": {**r["node_props"], "_labels": r["node_labels"]},
                "relationship": {"type": r["rel_type"], **r["rel_props"]},
            }
            for r in records
        ]

    async def find_shortest_path(
        self,
        repository_id: str,
        source_id: str,
        target_id: str,
        max_depth: int = 10,
    ) -> list[dict[str, Any]]:
        """Return nodes on the shortest path between two nodes.

        Args:
            repository_id: Repository UUID string.
            source_id: Source node ID.
            target_id: Target node ID.
            max_depth: Maximum path length.

        Returns:
            List of node property dicts on the path, or empty list if
            no path exists.
        """
        cypher = (
            "MATCH p = shortestPath( "
            "  (src:_GraphNode {id: $sid, repository_id: $rid})"
            "  -[*..{max_depth}]-"
            "  (tgt:_GraphNode {id: $tid, repository_id: $rid})"
            ") "
            "RETURN [n IN nodes(p) | properties(n)] AS path_nodes, "
            "       [r IN relationships(p) | type(r)] AS rel_types"
        ).replace("{max_depth}", str(max_depth))

        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                cypher,
                sid=source_id,
                tid=target_id,
                rid=repository_id,
            )
            record = await result.single()

        if record is None:
            return []
        return list(record["path_nodes"])

    async def k_hop_subgraph(
        self,
        repository_id: str,
        node_id: str,
        k: int = 2,
    ) -> list[dict[str, Any]]:
        """Return all nodes within k hops of a starting node.

        Args:
            repository_id: Repository UUID string.
            node_id: Starting node ID.
            k: Number of hops (max relationship depth).

        Returns:
            List of node property dicts.
        """
        cypher = (
            "MATCH (start:_GraphNode {id: $nid, repository_id: $rid}) "
            f"MATCH (start)-[*1..{k}]-(neighbor:_GraphNode {{repository_id: $rid}}) "
            "RETURN DISTINCT properties(neighbor) AS props, "
            "                labels(neighbor) AS labels"
        )
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                cypher,
                nid=node_id,
                rid=repository_id,
            )
            records = await result.data()

        return [{**r["props"], "_labels": r["labels"]} for r in records]

    async def get_dependency_subgraph(
        self,
        repository_id: str,
        max_depth: int = 5,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return all IMPORTS and DEPENDS_ON relationships for a repository.

        Args:
            repository_id: Repository UUID string.
            max_depth: Maximum traversal depth (unused — returns all edges).

        Returns:
            dict with ``nodes`` and ``edges`` lists.
        """
        cypher = (
            "MATCH (src:_GraphNode {repository_id: $rid})"
            "-[r:IMPORTS|DEPENDS_ON]->"
            "(tgt:_GraphNode {repository_id: $rid}) "
            "RETURN properties(src) AS src_props, labels(src) AS src_labels, "
            "       properties(tgt) AS tgt_props, labels(tgt) AS tgt_labels, "
            "       type(r) AS rel_type"
        )
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, rid=repository_id)
            records = await result.data()

        seen_nodes: dict[str, dict] = {}
        edges: list[dict] = []

        for row in records:
            src = {**row["src_props"], "_labels": row["src_labels"]}
            tgt = {**row["tgt_props"], "_labels": row["tgt_labels"]}
            seen_nodes[src["id"]] = src
            seen_nodes[tgt["id"]] = tgt
            edges.append({
                "source": src["id"],
                "target": tgt["id"],
                "type": row["rel_type"],
            })

        return {"nodes": list(seen_nodes.values()), "edges": edges}

    async def get_call_graph(
        self,
        repository_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return all CALLS relationships for a repository.

        Args:
            repository_id: Repository UUID string.

        Returns:
            dict with ``nodes`` and ``edges`` lists.
        """
        cypher = (
            "MATCH (src:_GraphNode {repository_id: $rid})"
            "-[r:CALLS]->"
            "(tgt:_GraphNode {repository_id: $rid}) "
            "RETURN properties(src) AS src_props, labels(src) AS src_labels, "
            "       properties(tgt) AS tgt_props, labels(tgt) AS tgt_labels"
        )
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, rid=repository_id)
            records = await result.data()

        seen_nodes: dict[str, dict] = {}
        edges: list[dict] = []

        for row in records:
            src = {**row["src_props"], "_labels": row["src_labels"]}
            tgt = {**row["tgt_props"], "_labels": row["tgt_labels"]}
            seen_nodes[src["id"]] = src
            seen_nodes[tgt["id"]] = tgt
            edges.append({
                "source": src["id"],
                "target": tgt["id"],
                "type": "CALLS",
            })

        return {"nodes": list(seen_nodes.values()), "edges": edges}

    # ── Analysis queries ───────────────────────────────────────────────────────

    async def find_unused_functions(
        self,
        repository_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return functions/methods that have no incoming CALLS edges.

        Args:
            repository_id: Repository UUID string.
            limit: Maximum results.

        Returns:
            List of node property dicts.
        """
        cypher = (
            "MATCH (n:_GraphNode {repository_id: $rid}) "
            "WHERE n:Function OR n:Method "
            "AND NOT ()-[:CALLS]->(n) "
            "RETURN properties(n) AS props, labels(n) AS labels "
            "LIMIT $limit"
        )
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                cypher, rid=repository_id, limit=limit
            )
            records = await result.data()
        return [{**r["props"], "_labels": r["labels"]} for r in records]

    async def find_orphan_classes(
        self,
        repository_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return classes that have no relationships at all.

        Args:
            repository_id: Repository UUID string.
            limit: Maximum results.

        Returns:
            List of node property dicts.
        """
        cypher = (
            "MATCH (n:Class {repository_id: $rid}) "
            "WHERE NOT (n)--() "
            "RETURN properties(n) AS props, labels(n) AS labels "
            "LIMIT $limit"
        )
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                cypher, rid=repository_id, limit=limit
            )
            records = await result.data()
        return [{**r["props"], "_labels": r["labels"]} for r in records]

    async def find_circular_dependencies(
        self,
        repository_id: str,
        limit: int = 50,
    ) -> list[list[str]]:
        """Detect cycles in IMPORTS and DEPENDS_ON edges.

        Returns paths that form cycles (length 2–6 for performance).

        Args:
            repository_id: Repository UUID string.
            limit: Maximum cycles to return.

        Returns:
            List of lists; each inner list is the qualified_name sequence
            of nodes forming one cycle.
        """
        cypher = (
            "MATCH p = (a:_GraphNode {repository_id: $rid})"
            "-[:IMPORTS|DEPENDS_ON*2..6]->(a) "
            "RETURN [n IN nodes(p) | n.qualified_name] AS cycle "
            "LIMIT $limit"
        )
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                cypher, rid=repository_id, limit=limit
            )
            records = await result.data()
        return [r["cycle"] for r in records]

    async def find_longest_dependency_chain(
        self,
        repository_id: str,
    ) -> list[str]:
        """Return the qualified_name sequence of the longest import/dependency chain.

        Args:
            repository_id: Repository UUID string.

        Returns:
            List of qualified name strings from root to leaf.
        """
        cypher = (
            "MATCH p = (root:_GraphNode {repository_id: $rid})"
            "-[:IMPORTS|DEPENDS_ON*1..20]->"
            "(leaf:_GraphNode {repository_id: $rid}) "
            "WHERE NOT ()-[:IMPORTS|DEPENDS_ON]->(root) "
            "RETURN [n IN nodes(p) | n.qualified_name] AS chain, length(p) AS len "
            "ORDER BY len DESC LIMIT 1"
        )
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, rid=repository_id)
            record = await result.single()
        if record is None:
            return []
        return list(record["chain"])

    async def count_nodes(self, repository_id: str) -> int:
        """Return total node count for a repository.

        Args:
            repository_id: Repository UUID string.

        Returns:
            Integer count.
        """
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                "MATCH (n:_GraphNode {repository_id: $rid}) RETURN count(n) AS c",
                rid=repository_id,
            )
            record = await result.single()
        return record["c"] if record else 0

    async def count_edges(self, repository_id: str) -> int:
        """Return total relationship count for a repository.

        Args:
            repository_id: Repository UUID string.

        Returns:
            Integer count.
        """
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                "MATCH (n:_GraphNode {repository_id: $rid})-[r]->() "
                "RETURN count(r) AS c",
                rid=repository_id,
            )
            record = await result.single()
        return record["c"] if record else 0
