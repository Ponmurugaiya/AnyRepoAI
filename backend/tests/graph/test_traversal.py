"""Tests for the GraphTraversal algorithms.

Verifies BFS, DFS, shortest-path, k-hop, and dependency expansion
on simple in-memory edge lists.
"""

from __future__ import annotations

import pytest

from backend.app.graph.models.nodes import EdgeType, GraphEdge
from backend.app.graph.traversals.algorithms import GraphTraversal

REPO_ID = "test-repo"


def _e(src: str, tgt: str, etype: EdgeType = EdgeType.CALLS) -> GraphEdge:
    return GraphEdge(
        source_id=src,
        target_id=tgt,
        edge_type=etype,
        repository_id=REPO_ID,
    )


# ── Test graph topology ────────────────────────────────────────────────────────
#
#   A → B → D
#   A → C → D
#   D → E


GRAPH_EDGES = [
    _e("A", "B"),
    _e("A", "C"),
    _e("B", "D"),
    _e("C", "D"),
    _e("D", "E"),
]


class TestBFS:
    def test_visits_all_reachable(self) -> None:
        result = GraphTraversal.bfs("A", GRAPH_EDGES)
        assert set(result) == {"B", "C", "D", "E"}

    def test_order_breadth_first(self) -> None:
        result = GraphTraversal.bfs("A", GRAPH_EDGES)
        # B and C must appear before D; D before E
        assert result.index("D") > result.index("B")
        assert result.index("E") > result.index("D")

    def test_max_depth_limits_traversal(self) -> None:
        result = GraphTraversal.bfs("A", GRAPH_EDGES, max_depth=1)
        assert set(result) == {"B", "C"}
        assert "D" not in result

    def test_unreachable_node_excluded(self) -> None:
        result = GraphTraversal.bfs("E", GRAPH_EDGES)
        assert result == []

    def test_edge_type_filter(self) -> None:
        import_edges = [
            _e("A", "B", EdgeType.IMPORTS),
            _e("A", "C", EdgeType.CALLS),
        ]
        result = GraphTraversal.bfs(
            "A", import_edges, edge_types={EdgeType.IMPORTS}
        )
        assert "B" in result
        assert "C" not in result


class TestDFS:
    def test_visits_all_reachable(self) -> None:
        result = GraphTraversal.dfs("A", GRAPH_EDGES)
        assert set(result) == {"B", "C", "D", "E"}

    def test_max_depth_limits(self) -> None:
        result = GraphTraversal.dfs("A", GRAPH_EDGES, max_depth=1)
        assert "E" not in result

    def test_empty_when_no_outgoing(self) -> None:
        result = GraphTraversal.dfs("E", GRAPH_EDGES)
        assert result == []


class TestShortestPath:
    def test_direct_path(self) -> None:
        path = GraphTraversal.shortest_path("A", "B", GRAPH_EDGES)
        assert path == ["A", "B"]

    def test_indirect_path(self) -> None:
        path = GraphTraversal.shortest_path("A", "E", GRAPH_EDGES)
        assert path[0] == "A"
        assert path[-1] == "E"
        assert len(path) == 4  # A→B→D→E or A→C→D→E

    def test_same_source_and_target(self) -> None:
        path = GraphTraversal.shortest_path("A", "A", GRAPH_EDGES)
        assert path == ["A"]

    def test_no_path_returns_empty(self) -> None:
        path = GraphTraversal.shortest_path("E", "A", GRAPH_EDGES)
        assert path == []

    def test_edge_type_filter_restricts_path(self) -> None:
        import_only = [_e("A", "B", EdgeType.IMPORTS)]
        path = GraphTraversal.shortest_path(
            "A", "C", import_only, edge_types={EdgeType.IMPORTS}
        )
        assert path == []

    def test_minimum_length_path_chosen(self) -> None:
        # A→B→D and A→D both exist; shortest is A→D
        edges = GRAPH_EDGES + [_e("A", "D")]
        path = GraphTraversal.shortest_path("A", "D", edges)
        assert len(path) == 2  # A→D directly


class TestKHop:
    def test_1_hop_neighbors(self) -> None:
        result = GraphTraversal.k_hop("A", GRAPH_EDGES, k=1)
        assert result == {"B", "C"}

    def test_2_hop_includes_grandchildren(self) -> None:
        result = GraphTraversal.k_hop("A", GRAPH_EDGES, k=2)
        assert "D" in result
        assert "B" in result

    def test_3_hop_reaches_leaf(self) -> None:
        result = GraphTraversal.k_hop("A", GRAPH_EDGES, k=3)
        assert "E" in result

    def test_start_not_in_result(self) -> None:
        result = GraphTraversal.k_hop("A", GRAPH_EDGES, k=2)
        assert "A" not in result

    def test_direction_incoming(self) -> None:
        result = GraphTraversal.k_hop("E", GRAPH_EDGES, k=1, direction="incoming")
        assert "D" in result

    def test_zero_hop_empty(self) -> None:
        result = GraphTraversal.k_hop("A", GRAPH_EDGES, k=0)
        assert result == set()


class TestExpandDependencies:
    def test_expands_import_chain(self) -> None:
        edges = [
            _e("app", "auth", EdgeType.IMPORTS),
            _e("auth", "jwt", EdgeType.IMPORTS),
            _e("jwt", "crypto", EdgeType.IMPORTS),
        ]
        result = GraphTraversal.expand_dependencies("app", edges)
        node_ids = {r[0] for r in result}
        assert node_ids == {"auth", "jwt", "crypto"}

    def test_depth_recorded(self) -> None:
        edges = [
            _e("A", "B", EdgeType.IMPORTS),
            _e("B", "C", EdgeType.IMPORTS),
        ]
        result = GraphTraversal.expand_dependencies("A", edges)
        depth_map = {r[0]: r[1] for r in result}
        assert depth_map["B"] == 1
        assert depth_map["C"] == 2

    def test_max_depth_respected(self) -> None:
        edges = [
            _e("A", "B", EdgeType.IMPORTS),
            _e("B", "C", EdgeType.IMPORTS),
            _e("C", "D", EdgeType.IMPORTS),
        ]
        result = GraphTraversal.expand_dependencies("A", edges, max_depth=2)
        node_ids = {r[0] for r in result}
        assert "D" not in node_ids

    def test_calls_edges_excluded(self) -> None:
        edges = [_e("A", "B", EdgeType.CALLS)]
        result = GraphTraversal.expand_dependencies("A", edges)
        assert result == []


class TestExtractSubgraph:
    def test_returns_only_internal_edges(self) -> None:
        edges = GRAPH_EDGES  # A→B, A→C, B→D, C→D, D→E
        subgraph_nodes = {"A", "B", "C"}
        result = GraphTraversal.extract_subgraph(subgraph_nodes, edges)
        for e in result:
            assert e.source_id in subgraph_nodes
            assert e.target_id in subgraph_nodes

    def test_excludes_edges_crossing_boundary(self) -> None:
        subgraph_nodes = {"A", "B"}
        result = GraphTraversal.extract_subgraph(subgraph_nodes, GRAPH_EDGES)
        # Only A→B crosses no boundary
        assert len(result) == 1
        assert result[0].source_id == "A"
        assert result[0].target_id == "B"

    def test_empty_node_set_returns_empty(self) -> None:
        result = GraphTraversal.extract_subgraph(set(), GRAPH_EDGES)
        assert result == []
