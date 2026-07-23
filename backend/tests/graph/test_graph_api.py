"""Integration tests for the Knowledge Graph REST API.

Tests all graph endpoints using the self-contained test client from conftest.py.
All Neo4j and service layer calls are mocked per-test.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from backend.app.core.exceptions import RepositoryNotFoundError
from backend.app.graph.schemas.graph import (
    GraphBuildProgress,
    GraphBuildResponse,
    GraphStatistics,
    GraphSubgraphResponse,
)

REPO_ID = uuid.uuid4()
NODE_ID = str(uuid.uuid4())

_ROUTER_PATH = "backend.app.graph.api.router"


def _make_node_record(**overrides) -> dict:
    base = {
        "id": NODE_ID,
        "name": "login",
        "qualified_name": "app.auth.AuthService.login",
        "language": "Python",
        "file_path": "app/auth.py",
        "repository_id": str(REPO_ID),
        "_labels": ["Method", "_GraphNode"],
    }
    base.update(overrides)
    return base


class TestBuildGraph:
    """POST /repositories/{id}/graph/build"""

    @pytest.mark.asyncio
    async def test_returns_202(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}._enqueue_build"):
            response = await client.post(
                f"/api/v1/repositories/{REPO_ID}/graph/build"
            )
        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_response_data_queued(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}._enqueue_build"):
            response = await client.post(
                f"/api/v1/repositories/{REPO_ID}/graph/build"
            )
        body = response.json()
        assert body["success"] is True
        assert body["data"]["status"] == "QUEUED"

    @pytest.mark.asyncio
    async def test_enqueue_called(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}._enqueue_build") as mock_enqueue:
            await client.post(f"/api/v1/repositories/{REPO_ID}/graph/build")
        mock_enqueue.assert_called_once()


class TestGetGraphProgress:
    """GET /repositories/{id}/graph/progress"""

    @pytest.mark.asyncio
    async def test_returns_200_with_progress(self, client: AsyncClient) -> None:
        progress = GraphBuildProgress(
            repository_id=REPO_ID,
            status="COMPLETED",
            total_nodes=250,
            total_edges=800,
        )
        with patch(f"{_ROUTER_PATH}.GraphBuildService") as MockSvc:
            mock_svc = AsyncMock()
            mock_svc.get_progress.return_value = progress
            MockSvc.return_value = mock_svc
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/progress"
                )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["total_nodes"] == 250
        assert body["data"]["total_edges"] == 800

    @pytest.mark.asyncio
    async def test_returns_404_when_not_found(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}.GraphBuildService") as MockSvc:
            mock_svc = AsyncMock()
            mock_svc.get_progress.side_effect = RepositoryNotFoundError(str(REPO_ID))
            MockSvc.return_value = mock_svc
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/progress"
                )
        assert response.status_code == 404


class TestGetNode:
    """GET /repositories/{id}/graph/node/{node_id}"""

    @pytest.mark.asyncio
    async def test_returns_200_when_found(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}.GraphRepository") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.get_node.return_value = _make_node_record()
            MockRepo.return_value = mock_repo
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/node/{NODE_ID}"
                )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["node_id"] == NODE_ID

    @pytest.mark.asyncio
    async def test_returns_404_when_not_found(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}.GraphRepository") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.get_node.return_value = None
            MockRepo.return_value = mock_repo
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/node/nonexistent"
                )
        assert response.status_code == 404


class TestGetNeighbors:
    """GET /repositories/{id}/graph/neighbors/{node_id}"""

    @pytest.mark.asyncio
    async def test_returns_200_with_empty_list(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}.GraphRepository") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.get_neighbors.return_value = []
            MockRepo.return_value = mock_repo
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/neighbors/{NODE_ID}"
                )
        assert response.status_code == 200
        assert response.json()["data"] == []

    @pytest.mark.asyncio
    async def test_direction_param_accepted(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}.GraphRepository") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.get_neighbors.return_value = []
            MockRepo.return_value = mock_repo
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/neighbors/{NODE_ID}",
                    params={"direction": "outgoing"},
                )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_limit_out_of_range_rejected(self, client: AsyncClient) -> None:
        response = await client.get(
            f"/api/v1/repositories/{REPO_ID}/graph/neighbors/{NODE_ID}",
            params={"limit": "0"},
        )
        assert response.status_code == 422


class TestFindPath:
    """GET /repositories/{id}/graph/path"""

    @pytest.mark.asyncio
    async def test_returns_path_when_found(self, client: AsyncClient) -> None:
        path_nodes = [{"id": "A", "name": "A"}, {"id": "B", "name": "B"}]
        with patch(f"{_ROUTER_PATH}.GraphRepository") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.find_shortest_path.return_value = path_nodes
            MockRepo.return_value = mock_repo
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/path",
                    params={"source": "A", "target": "B"},
                )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["found"] is True
        assert body["data"]["length"] == 1

    @pytest.mark.asyncio
    async def test_returns_not_found_when_no_path(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}.GraphRepository") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.find_shortest_path.return_value = []
            MockRepo.return_value = mock_repo
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/path",
                    params={"source": "X", "target": "Y"},
                )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["found"] is False

    @pytest.mark.asyncio
    async def test_source_required(self, client: AsyncClient) -> None:
        response = await client.get(
            f"/api/v1/repositories/{REPO_ID}/graph/path",
            params={"target": "B"},
        )
        assert response.status_code == 422


class TestDependencyGraph:
    """GET /repositories/{id}/graph/dependencies"""

    @pytest.mark.asyncio
    async def test_returns_subgraph(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}.GraphRepository") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.get_dependency_subgraph.return_value = {
                "nodes": [{"id": "A"}, {"id": "B"}],
                "edges": [{"source": "A", "target": "B", "type": "IMPORTS"}],
            }
            MockRepo.return_value = mock_repo
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/dependencies"
                )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["node_count"] == 2
        assert body["data"]["edge_count"] == 1


class TestCallGraph:
    """GET /repositories/{id}/graph/callgraph"""

    @pytest.mark.asyncio
    async def test_returns_call_subgraph(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}.GraphRepository") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.get_call_graph.return_value = {"nodes": [], "edges": []}
            MockRepo.return_value = mock_repo
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/callgraph"
                )
        assert response.status_code == 200


class TestAnalysisEndpoints:
    """GET /repositories/{id}/graph/analysis/*"""

    @pytest.mark.asyncio
    async def test_unused_functions_200(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}.GraphRepository") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.find_unused_functions.return_value = []
            MockRepo.return_value = mock_repo
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/analysis/unused-functions"
                )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["analysis_type"] == "unused_functions"

    @pytest.mark.asyncio
    async def test_orphan_classes_200(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}.GraphRepository") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.find_orphan_classes.return_value = []
            MockRepo.return_value = mock_repo
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/analysis/orphan-classes"
                )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_circular_dependencies_200(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}.GraphRepository") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.find_circular_dependencies.return_value = [
                ["A", "B", "A"]
            ]
            MockRepo.return_value = mock_repo
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/analysis/circular-dependencies"
                )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["total"] == 1

    @pytest.mark.asyncio
    async def test_longest_chain_200(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}.GraphRepository") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.find_longest_dependency_chain.return_value = [
                "app", "auth", "jwt", "crypto"
            ]
            MockRepo.return_value = mock_repo
            with patch(f"{_ROUTER_PATH}._get_neo4j_driver", return_value=MagicMock()):
                response = await client.get(
                    f"/api/v1/repositories/{REPO_ID}/graph/analysis/longest-chain"
                )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["total"] == 4
