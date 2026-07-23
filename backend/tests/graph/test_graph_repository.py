"""Tests for the GraphRepository data-access layer.

Uses mocked Neo4j AsyncDriver to verify query construction and result
handling without requiring a live Neo4j instance.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.graph.models.nodes import EdgeType, GraphEdge, GraphNode, NodeType

REPO_ID = "test-repo-id"


def _make_driver() -> MagicMock:
    """Return a mock AsyncDriver whose session() returns an async context manager."""
    driver = MagicMock()
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock()
    session_cm.__aexit__ = AsyncMock(return_value=False)

    # Default run() result: nothing returned
    run_result = AsyncMock()
    run_result.data = AsyncMock(return_value=[])
    run_result.single = AsyncMock(return_value=None)
    session_cm.__aenter__.return_value.run = AsyncMock(return_value=run_result)
    driver.session = MagicMock(return_value=session_cm)
    return driver


def _node(node_id: str, label: str = "Function") -> GraphNode:
    return GraphNode(
        node_id=node_id,
        node_type=NodeType.FUNCTION,
        repository_id=REPO_ID,
        name=node_id,
        qualified_name=node_id,
    )


def _edge(src: str, tgt: str, etype: EdgeType = EdgeType.CALLS) -> GraphEdge:
    return GraphEdge(
        source_id=src,
        target_id=tgt,
        edge_type=etype,
        repository_id=REPO_ID,
    )


class TestMergeNodes:
    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self) -> None:
        from backend.app.graph.repositories.graph_repository import GraphRepository

        repo = GraphRepository(_make_driver())
        count = await repo.merge_nodes([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_single_node_calls_execute(self) -> None:
        driver = _make_driver()
        from backend.app.graph.repositories.graph_repository import GraphRepository

        repo = GraphRepository(driver)
        count = await repo.merge_nodes([_node("n1")])
        assert count == 1
        # session().run was called
        driver.session().__aenter__.return_value.run.assert_called()

    @pytest.mark.asyncio
    async def test_groups_by_label(self) -> None:
        """Nodes with different labels should each get their own Cypher call."""
        driver = _make_driver()
        from backend.app.graph.repositories.graph_repository import GraphRepository

        repo = GraphRepository(driver)
        func_node = _node("n1")
        class_node = GraphNode(
            node_id="n2",
            node_type=NodeType.CLASS,
            repository_id=REPO_ID,
            name="MyClass",
            qualified_name="MyClass",
        )
        count = await repo.merge_nodes([func_node, class_node])
        assert count == 2


class TestMergeEdges:
    @pytest.mark.asyncio
    async def test_empty_list_returns_zero(self) -> None:
        from backend.app.graph.repositories.graph_repository import GraphRepository

        repo = GraphRepository(_make_driver())
        count = await repo.merge_edges([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_single_edge_calls_execute(self) -> None:
        driver = _make_driver()
        from backend.app.graph.repositories.graph_repository import GraphRepository

        repo = GraphRepository(driver)
        count = await repo.merge_edges([_edge("A", "B")])
        assert count == 1

    @pytest.mark.asyncio
    async def test_different_types_grouped(self) -> None:
        driver = _make_driver()
        from backend.app.graph.repositories.graph_repository import GraphRepository

        repo = GraphRepository(driver)
        edges = [
            _edge("A", "B", EdgeType.CALLS),
            _edge("C", "D", EdgeType.IMPORTS),
        ]
        count = await repo.merge_edges(edges)
        assert count == 2


class TestDeleteOperations:
    @pytest.mark.asyncio
    async def test_delete_repository_graph_calls_run(self) -> None:
        driver = _make_driver()
        from backend.app.graph.repositories.graph_repository import GraphRepository

        repo = GraphRepository(driver)
        await repo.delete_repository_graph(REPO_ID)
        driver.session().__aenter__.return_value.run.assert_called()

    @pytest.mark.asyncio
    async def test_delete_file_nodes_calls_run(self) -> None:
        driver = _make_driver()
        from backend.app.graph.repositories.graph_repository import GraphRepository

        repo = GraphRepository(driver)
        await repo.delete_file_nodes(REPO_ID, "src/auth.py")
        driver.session().__aenter__.return_value.run.assert_called()


class TestGetNode:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        from backend.app.graph.repositories.graph_repository import GraphRepository

        repo = GraphRepository(_make_driver())
        result = await repo.get_node(REPO_ID, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_dict_when_found(self) -> None:
        driver = _make_driver()
        record = MagicMock()
        record.__getitem__ = MagicMock(side_effect=lambda k: {
            "props": {"id": "n1", "name": "func"},
            "labels": ["Function", "_GraphNode"],
        }[k])

        run_result = AsyncMock()
        run_result.single = AsyncMock(return_value=record)
        driver.session().__aenter__.return_value.run = AsyncMock(
            return_value=run_result
        )

        from backend.app.graph.repositories.graph_repository import GraphRepository

        repo = GraphRepository(driver)
        result = await repo.get_node(REPO_ID, "n1")
        assert result is not None


class TestCountOperations:
    @pytest.mark.asyncio
    async def test_count_nodes_returns_integer(self) -> None:
        driver = _make_driver()
        record = MagicMock()
        record.__getitem__ = MagicMock(return_value=42)

        run_result = AsyncMock()
        run_result.single = AsyncMock(return_value=record)
        driver.session().__aenter__.return_value.run = AsyncMock(
            return_value=run_result
        )

        from backend.app.graph.repositories.graph_repository import GraphRepository

        repo = GraphRepository(driver)
        count = await repo.count_nodes(REPO_ID)
        assert count == 42

    @pytest.mark.asyncio
    async def test_count_edges_returns_zero_when_none(self) -> None:
        from backend.app.graph.repositories.graph_repository import GraphRepository

        repo = GraphRepository(_make_driver())
        count = await repo.count_edges(REPO_ID)
        assert count == 0
