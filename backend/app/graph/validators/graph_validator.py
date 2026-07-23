"""Graph relationship and integrity validators.

The :class:`GraphValidator` catches structural problems in graph data
*before* they reach Neo4j so bad data is logged and skipped rather than
corrupting the graph.

Validation rules:
    - Edge source and target must both be non-empty strings.
    - Edge source and target must differ (no self-loops except CALLS).
    - Edge type must be a known :class:`~backend.app.graph.models.nodes.EdgeType`.
    - Node ``node_id`` and ``qualified_name`` must be non-empty.
    - Circular dependency detection operates on the in-memory edge list
      using iterative DFS.
"""

from __future__ import annotations

from collections import defaultdict, deque

from backend.app.core.logging import get_logger
from backend.app.graph.models.nodes import EdgeType, GraphEdge, GraphNode

logger = get_logger(__name__)


class GraphValidator:
    """Validates graph nodes and edges before Neo4j persistence.

    All methods are pure and stateless; safe for concurrent use.

    Example::

        validator = GraphValidator()
        clean_nodes = validator.filter_nodes(raw_nodes)
        clean_edges = validator.filter_edges(raw_edges, known_ids)
    """

    # ── Node validation ────────────────────────────────────────────────────────

    @staticmethod
    def filter_nodes(nodes: list[GraphNode]) -> list[GraphNode]:
        """Remove invalid nodes and return the clean list.

        A node is invalid when:
        - ``node_id`` is empty or blank.
        - ``qualified_name`` is empty or blank.
        - ``name`` is empty or blank.

        Args:
            nodes: Raw node list.

        Returns:
            Filtered list of valid :class:`GraphNode` objects.
        """
        valid: list[GraphNode] = []
        dropped = 0
        for node in nodes:
            if not (node.node_id.strip() and node.qualified_name.strip() and node.name.strip()):
                dropped += 1
                logger.debug(
                    "Invalid node dropped",
                    node_id=node.node_id,
                    qualified_name=node.qualified_name,
                )
                continue
            valid.append(node)

        if dropped:
            logger.warning(
                "Invalid nodes dropped during validation",
                dropped=dropped,
                total_input=len(nodes),
            )
        return valid

    # ── Edge validation ────────────────────────────────────────────────────────

    @staticmethod
    def filter_edges(
        edges: list[GraphEdge],
        known_node_ids: set[str],
    ) -> list[GraphEdge]:
        """Remove invalid edges and return the clean list.

        An edge is invalid when:
        - ``source_id`` or ``target_id`` is empty.
        - Source or target is not in ``known_node_ids`` (broken reference).
        - Self-loop on a non-CALLS edge type.

        Args:
            edges: Raw edge list.
            known_node_ids: Set of valid node IDs that exist in the current
                build context.

        Returns:
            Filtered list of valid :class:`GraphEdge` objects.
        """
        valid: list[GraphEdge] = []
        dropped_missing = 0
        dropped_self = 0

        for edge in edges:
            if not edge.source_id.strip() or not edge.target_id.strip():
                dropped_missing += 1
                continue

            if edge.source_id not in known_node_ids:
                dropped_missing += 1
                continue

            if edge.target_id not in known_node_ids:
                # Target may be an external library node; skip silently
                dropped_missing += 1
                continue

            # Self-loops only make sense for CALLS (rare recursive case)
            if (
                edge.source_id == edge.target_id
                and edge.edge_type != EdgeType.CALLS
            ):
                dropped_self += 1
                logger.debug(
                    "Self-loop edge dropped",
                    source=edge.source_id,
                    edge_type=edge.edge_type.value,
                )
                continue

            valid.append(edge)

        if dropped_missing or dropped_self:
            logger.warning(
                "Invalid edges dropped during validation",
                dropped_missing=dropped_missing,
                dropped_self_loops=dropped_self,
                total_input=len(edges),
            )
        return valid

    # ── Circular dependency detection ─────────────────────────────────────────

    @staticmethod
    def detect_cycles(
        edges: list[GraphEdge],
        *,
        edge_types: set[EdgeType] | None = None,
    ) -> list[list[str]]:
        """Detect cycles in a directed graph using iterative DFS.

        Only edges whose ``edge_type`` is in ``edge_types`` are considered.
        Defaults to IMPORTS and DEPENDS_ON.

        Args:
            edges: Edge list to analyse.
            edge_types: Edge types to include in cycle detection.
                        Defaults to ``{IMPORTS, DEPENDS_ON}``.

        Returns:
            List of cycles; each cycle is a list of ``node_id`` strings
            forming the cycle path (first and last element are the same).
        """
        if edge_types is None:
            edge_types = {EdgeType.IMPORTS, EdgeType.DEPENDS_ON}

        # Build adjacency list
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            if edge.edge_type in edge_types:
                adjacency[edge.source_id].append(edge.target_id)

        visited: set[str] = set()
        rec_stack: set[str] = set()
        cycles: list[list[str]] = []

        def _dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbour in adjacency.get(node, []):
                if neighbour not in visited:
                    _dfs(neighbour, path)
                elif neighbour in rec_stack:
                    # Found cycle: extract the cycle portion from path
                    cycle_start = path.index(neighbour)
                    cycles.append(path[cycle_start:] + [neighbour])

            path.pop()
            rec_stack.discard(node)

        all_nodes = set(adjacency.keys())
        for node in all_nodes:
            if node not in visited:
                _dfs(node, [])

        if cycles:
            logger.warning(
                "Circular dependencies detected",
                cycle_count=len(cycles),
            )

        return cycles
