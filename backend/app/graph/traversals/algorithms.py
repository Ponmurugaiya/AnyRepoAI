"""In-memory graph traversal algorithms.

:class:`GraphTraversal` operates on adjacency-list representations derived
from :class:`~backend.app.graph.models.nodes.GraphEdge` lists.  All
algorithms run in-process on data returned from Neo4j queries, enabling
Python-level traversal without additional Cypher round-trips.

Algorithms provided:
    - BFS (breadth-first search)
    - DFS (depth-first search)
    - Shortest path (BFS-based, unweighted)
    - k-hop subgraph extraction
    - Dependency expansion (transitive closure)
"""

from __future__ import annotations

from collections import deque
from typing import Any

from backend.app.core.logging import get_logger
from backend.app.graph.models.nodes import EdgeType, GraphEdge

logger = get_logger(__name__)


# ── Adjacency list helpers ─────────────────────────────────────────────────────


def _build_adjacency(
    edges: list[GraphEdge],
    *,
    edge_types: set[EdgeType] | None = None,
    direction: str = "outgoing",
) -> dict[str, list[str]]:
    """Build an adjacency list from a flat edge list.

    Args:
        edges: All edges to consider.
        edge_types: Optional filter; ``None`` means all types.
        direction: ``"outgoing"`` (src→tgt), ``"incoming"`` (tgt→src),
                   or ``"both"``.

    Returns:
        dict mapping node_id → list of neighbour node_ids.
    """
    adj: dict[str, list[str]] = {}
    for edge in edges:
        if edge_types and edge.edge_type not in edge_types:
            continue
        if direction in ("outgoing", "both"):
            adj.setdefault(edge.source_id, []).append(edge.target_id)
        if direction in ("incoming", "both"):
            adj.setdefault(edge.target_id, []).append(edge.source_id)
    return adj


class GraphTraversal:
    """In-memory traversal algorithms for the Code Knowledge Graph.

    All methods are static and operate on plain edge lists.  They are
    designed to post-process data already loaded from Neo4j rather than
    issuing additional Cypher queries.

    Example::

        edges = [GraphEdge(source_id="A", target_id="B", ...),
                 GraphEdge(source_id="B", target_id="C", ...)]
        path = GraphTraversal.shortest_path("A", "C", edges)
        # → ["A", "B", "C"]
    """

    # ── BFS ───────────────────────────────────────────────────────────────────

    @staticmethod
    def bfs(
        start: str,
        edges: list[GraphEdge],
        *,
        edge_types: set[EdgeType] | None = None,
        max_depth: int = 10,
    ) -> list[str]:
        """Breadth-first search from ``start``.

        Args:
            start: Starting node ID.
            edges: All directed edges.
            edge_types: Optional edge type filter.
            max_depth: Maximum traversal depth.

        Returns:
            List of node IDs visited in BFS order (excluding ``start``).
        """
        adj = _build_adjacency(edges, edge_types=edge_types, direction="outgoing")
        visited: set[str] = {start}
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        result: list[str] = []

        while queue:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbour in adj.get(node, []):
                if neighbour not in visited:
                    visited.add(neighbour)
                    result.append(neighbour)
                    queue.append((neighbour, depth + 1))

        logger.debug(
            "BFS traversal completed",
            start=start,
            visited=len(result),
            max_depth=max_depth,
        )
        return result

    # ── DFS ───────────────────────────────────────────────────────────────────

    @staticmethod
    def dfs(
        start: str,
        edges: list[GraphEdge],
        *,
        edge_types: set[EdgeType] | None = None,
        max_depth: int = 10,
    ) -> list[str]:
        """Depth-first search from ``start`` (iterative).

        Args:
            start: Starting node ID.
            edges: All directed edges.
            edge_types: Optional edge type filter.
            max_depth: Maximum traversal depth.

        Returns:
            List of node IDs visited in DFS order (excluding ``start``).
        """
        adj = _build_adjacency(edges, edge_types=edge_types, direction="outgoing")
        visited: set[str] = {start}
        stack: list[tuple[str, int]] = [(start, 0)]
        result: list[str] = []

        while stack:
            node, depth = stack.pop()
            if depth >= max_depth:
                continue
            for neighbour in reversed(adj.get(node, [])):
                if neighbour not in visited:
                    visited.add(neighbour)
                    result.append(neighbour)
                    stack.append((neighbour, depth + 1))

        logger.debug(
            "DFS traversal completed",
            start=start,
            visited=len(result),
        )
        return result

    # ── Shortest path ──────────────────────────────────────────────────────────

    @staticmethod
    def shortest_path(
        source: str,
        target: str,
        edges: list[GraphEdge],
        *,
        edge_types: set[EdgeType] | None = None,
    ) -> list[str]:
        """Return the shortest path from ``source`` to ``target`` using BFS.

        Args:
            source: Source node ID.
            target: Target node ID.
            edges: All directed edges.
            edge_types: Optional edge type filter.

        Returns:
            Ordered list of node IDs from ``source`` to ``target`` inclusive.
            Empty list if no path exists.
        """
        if source == target:
            return [source]

        adj = _build_adjacency(edges, edge_types=edge_types, direction="outgoing")
        visited: set[str] = {source}
        # Each queue entry: (current_node, path_so_far)
        queue: deque[tuple[str, list[str]]] = deque([(source, [source])])

        while queue:
            node, path = queue.popleft()
            for neighbour in adj.get(node, []):
                if neighbour == target:
                    return path + [neighbour]
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append((neighbour, path + [neighbour]))

        return []  # No path found

    # ── k-hop subgraph ─────────────────────────────────────────────────────────

    @staticmethod
    def k_hop(
        start: str,
        edges: list[GraphEdge],
        k: int = 2,
        *,
        edge_types: set[EdgeType] | None = None,
        direction: str = "both",
    ) -> set[str]:
        """Return all node IDs reachable within ``k`` hops from ``start``.

        Args:
            start: Starting node ID.
            edges: All edges.
            k: Maximum hops.
            edge_types: Optional edge type filter.
            direction: ``"outgoing"``, ``"incoming"``, or ``"both"``.

        Returns:
            Set of reachable node IDs (excluding ``start``).
        """
        adj = _build_adjacency(edges, edge_types=edge_types, direction=direction)
        visited: set[str] = {start}
        frontier = {start}

        for _ in range(k):
            next_frontier: set[str] = set()
            for node in frontier:
                for neighbour in adj.get(node, []):
                    if neighbour not in visited:
                        visited.add(neighbour)
                        next_frontier.add(neighbour)
            frontier = next_frontier
            if not frontier:
                break

        visited.discard(start)
        return visited

    # ── Dependency expansion ───────────────────────────────────────────────────

    @staticmethod
    def expand_dependencies(
        start: str,
        edges: list[GraphEdge],
        *,
        max_depth: int = 20,
    ) -> list[tuple[str, int]]:
        """Expand all transitive dependencies of a node.

        Traverses IMPORTS and DEPENDS_ON edges to build the full
        dependency closure.

        Args:
            start: Starting node ID.
            edges: All edges.
            max_depth: Maximum dependency chain depth.

        Returns:
            List of ``(node_id, depth)`` tuples in BFS order.
        """
        dep_types = {EdgeType.IMPORTS, EdgeType.DEPENDS_ON}
        adj = _build_adjacency(edges, edge_types=dep_types, direction="outgoing")
        visited: set[str] = {start}
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        result: list[tuple[str, int]] = []

        while queue:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbour in adj.get(node, []):
                if neighbour not in visited:
                    visited.add(neighbour)
                    result.append((neighbour, depth + 1))
                    queue.append((neighbour, depth + 1))

        return result

    # ── Subgraph extraction ────────────────────────────────────────────────────

    @staticmethod
    def extract_subgraph(
        node_ids: set[str],
        edges: list[GraphEdge],
    ) -> list[GraphEdge]:
        """Return only edges where both endpoints are in ``node_ids``.

        Args:
            node_ids: Set of node IDs to include.
            edges: Full edge list.

        Returns:
            Filtered edge list forming the induced subgraph.
        """
        return [
            e for e in edges
            if e.source_id in node_ids and e.target_id in node_ids
        ]
