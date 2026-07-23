"""Tests for the GraphValidator.

Verifies node/edge filtering and cycle detection.
"""

from __future__ import annotations

import pytest

from backend.app.graph.models.nodes import EdgeType, GraphEdge, GraphNode, NodeType
from backend.app.graph.validators.graph_validator import GraphValidator

REPO_ID = "repo-test"


def _node(node_id: str, name: str = "n", qname: str = "q") -> GraphNode:
    return GraphNode(
        node_id=node_id,
        node_type=NodeType.FUNCTION,
        repository_id=REPO_ID,
        name=name,
        qualified_name=qname,
    )


def _edge(
    src: str,
    tgt: str,
    edge_type: EdgeType = EdgeType.CALLS,
) -> GraphEdge:
    return GraphEdge(
        source_id=src,
        target_id=tgt,
        edge_type=edge_type,
        repository_id=REPO_ID,
    )


class TestFilterNodes:
    def test_valid_nodes_pass(self) -> None:
        nodes = [_node("n1", "func_a", "app.func_a")]
        result = GraphValidator.filter_nodes(nodes)
        assert len(result) == 1

    def test_empty_node_id_dropped(self) -> None:
        bad = _node("", "func_a", "app.func_a")
        result = GraphValidator.filter_nodes([bad])
        assert result == []

    def test_blank_node_id_dropped(self) -> None:
        bad = _node("   ", "func_a", "app.func_a")
        result = GraphValidator.filter_nodes([bad])
        assert result == []

    def test_empty_qualified_name_dropped(self) -> None:
        bad = GraphNode(
            node_id="n1",
            node_type=NodeType.FUNCTION,
            repository_id=REPO_ID,
            name="func",
            qualified_name="",
        )
        result = GraphValidator.filter_nodes([bad])
        assert result == []

    def test_empty_name_dropped(self) -> None:
        bad = GraphNode(
            node_id="n1",
            node_type=NodeType.FUNCTION,
            repository_id=REPO_ID,
            name="",
            qualified_name="app.func",
        )
        result = GraphValidator.filter_nodes([bad])
        assert result == []

    def test_mixed_valid_invalid(self) -> None:
        nodes = [
            _node("n1", "a", "a"),
            _node("", "b", "b"),   # invalid
            _node("n3", "c", "c"),
        ]
        result = GraphValidator.filter_nodes(nodes)
        assert len(result) == 2


class TestFilterEdges:
    def test_valid_edge_passes(self) -> None:
        e = _edge("A", "B")
        result = GraphValidator.filter_edges([e], {"A", "B"})
        assert len(result) == 1

    def test_source_not_in_known_dropped(self) -> None:
        e = _edge("X", "B")
        result = GraphValidator.filter_edges([e], {"A", "B"})
        assert result == []

    def test_target_not_in_known_dropped(self) -> None:
        e = _edge("A", "Z")
        result = GraphValidator.filter_edges([e], {"A", "B"})
        assert result == []

    def test_self_loop_non_calls_dropped(self) -> None:
        e = _edge("A", "A", EdgeType.IMPORTS)
        result = GraphValidator.filter_edges([e], {"A"})
        assert result == []

    def test_self_loop_calls_allowed(self) -> None:
        """CALLS self-loop (recursion) is allowed."""
        e = _edge("A", "A", EdgeType.CALLS)
        result = GraphValidator.filter_edges([e], {"A"})
        assert len(result) == 1

    def test_empty_source_dropped(self) -> None:
        e = GraphEdge(
            source_id="",
            target_id="B",
            edge_type=EdgeType.CALLS,
            repository_id=REPO_ID,
        )
        result = GraphValidator.filter_edges([e], {"", "B"})
        assert result == []

    def test_mixed_valid_invalid(self) -> None:
        edges = [
            _edge("A", "B"),   # valid
            _edge("A", "Z"),   # target unknown
            _edge("X", "B"),   # source unknown
            _edge("C", "D"),   # valid
        ]
        known = {"A", "B", "C", "D"}
        result = GraphValidator.filter_edges(edges, known)
        assert len(result) == 2


class TestDetectCycles:
    def test_simple_cycle_detected(self) -> None:
        edges = [
            _edge("A", "B", EdgeType.IMPORTS),
            _edge("B", "C", EdgeType.IMPORTS),
            _edge("C", "A", EdgeType.IMPORTS),
        ]
        cycles = GraphValidator.detect_cycles(edges)
        assert len(cycles) > 0

    def test_no_cycle_in_dag(self) -> None:
        edges = [
            _edge("A", "B", EdgeType.IMPORTS),
            _edge("B", "C", EdgeType.IMPORTS),
        ]
        cycles = GraphValidator.detect_cycles(edges)
        assert cycles == []

    def test_calls_edges_not_included_by_default(self) -> None:
        """CALLS edges are not traversed for cycle detection by default."""
        edges = [
            _edge("A", "B", EdgeType.CALLS),
            _edge("B", "A", EdgeType.CALLS),
        ]
        cycles = GraphValidator.detect_cycles(edges)
        assert cycles == []

    def test_depends_on_cycle_detected(self) -> None:
        edges = [
            _edge("A", "B", EdgeType.DEPENDS_ON),
            _edge("B", "A", EdgeType.DEPENDS_ON),
        ]
        cycles = GraphValidator.detect_cycles(edges)
        assert len(cycles) > 0

    def test_custom_edge_types(self) -> None:
        edges = [
            _edge("A", "B", EdgeType.CALLS),
            _edge("B", "A", EdgeType.CALLS),
        ]
        cycles = GraphValidator.detect_cycles(
            edges, edge_types={EdgeType.CALLS}
        )
        assert len(cycles) > 0

    def test_two_independent_cycles(self) -> None:
        edges = [
            _edge("A", "B", EdgeType.IMPORTS),
            _edge("B", "A", EdgeType.IMPORTS),
            _edge("C", "D", EdgeType.IMPORTS),
            _edge("D", "C", EdgeType.IMPORTS),
        ]
        cycles = GraphValidator.detect_cycles(edges)
        assert len(cycles) >= 2
