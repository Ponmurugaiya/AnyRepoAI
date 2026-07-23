"""Tests for the GraphBuildService orchestration layer.

Uses mocked Neo4j driver and PostgreSQL session to verify that the
service correctly calls each stage of the build pipeline and handles
error cases without crashing.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.core.exceptions import RepositoryNotFoundError
from backend.app.graph.schemas.graph import GraphBuildProgress, GraphStatistics
from backend.app.models.repository import RepositoryStatus

REPO_ID = uuid.uuid4()


def _make_mock_repo(
    repo_id: uuid.UUID | None = None,
    clone_status: RepositoryStatus = RepositoryStatus.READY,
) -> MagicMock:
    repo = MagicMock()
    repo.id = repo_id or REPO_ID
    repo.clone_status = clone_status
    repo.full_name = "owner/test-repo"
    repo.language = "Python"
    repo.description = "A test repo"
    return repo


def _make_mock_pg_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one.return_value = 0
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    return session


def _make_mock_neo4j() -> MagicMock:
    driver = MagicMock()
    return driver


class TestGraphBuildServiceValidation:
    """Verify validation guards in build_graph()."""

    @pytest.mark.asyncio
    async def test_raises_when_repo_not_found(self) -> None:
        session = _make_mock_pg_session()
        driver = _make_mock_neo4j()

        with patch(
            "backend.app.graph.services.graph_build_service.RepositoryRepository"
        ) as MockRepoRepo:
            mock_rr = AsyncMock()
            mock_rr.get_by_id.return_value = None
            MockRepoRepo.return_value = mock_rr

            from backend.app.graph.services.graph_build_service import GraphBuildService

            svc = GraphBuildService(pg_session=session, neo4j_driver=driver)
            with pytest.raises(RepositoryNotFoundError):
                await svc.build_graph(REPO_ID)

    @pytest.mark.asyncio
    async def test_returns_stats_on_empty_repo(self) -> None:
        """Empty repository (no files) completes without error."""
        session = _make_mock_pg_session()
        driver = _make_mock_neo4j()

        with (
            patch(
                "backend.app.graph.services.graph_build_service.RepositoryRepository"
            ) as MockRepoRepo,
            patch(
                "backend.app.graph.services.graph_build_service.FileRepository"
            ) as MockFileRepo,
            patch(
                "backend.app.graph.services.graph_build_service.GraphRepository"
            ) as MockGraphRepo,
            patch(
                "backend.app.graph.services.graph_build_service.SymbolIndexRepository"
            ) as MockIndexRepo,
        ):
            mock_rr = AsyncMock()
            mock_rr.get_by_id.return_value = _make_mock_repo()
            MockRepoRepo.return_value = mock_rr

            mock_fr = AsyncMock()
            mock_fr.get_by_repository_id.return_value = []
            MockFileRepo.return_value = mock_fr

            mock_gr = AsyncMock()
            mock_gr.ensure_indexes = AsyncMock()
            mock_gr.delete_repository_graph = AsyncMock()
            mock_gr.merge_nodes = AsyncMock(return_value=1)
            mock_gr.merge_edges = AsyncMock(return_value=0)
            MockGraphRepo.return_value = mock_gr

            mock_ir = AsyncMock()
            mock_ir.list_entries.return_value = []
            MockIndexRepo.return_value = mock_ir

            from backend.app.graph.services.graph_build_service import GraphBuildService

            svc = GraphBuildService(pg_session=session, neo4j_driver=driver)
            stats = await svc.build_graph(REPO_ID)

        assert isinstance(stats, GraphStatistics)
        assert stats.error_message is None


class TestGraphBuildServiceProgress:
    """Verify get_progress() returns Neo4j counts."""

    @pytest.mark.asyncio
    async def test_returns_progress_with_counts(self) -> None:
        session = _make_mock_pg_session()
        driver = _make_mock_neo4j()

        with (
            patch(
                "backend.app.graph.services.graph_build_service.RepositoryRepository"
            ) as MockRepoRepo,
            patch(
                "backend.app.graph.services.graph_build_service.GraphRepository"
            ) as MockGraphRepo,
        ):
            mock_rr = AsyncMock()
            mock_rr.get_by_id.return_value = _make_mock_repo()
            MockRepoRepo.return_value = mock_rr

            mock_gr = AsyncMock()
            mock_gr.count_nodes = AsyncMock(return_value=150)
            mock_gr.count_edges = AsyncMock(return_value=420)
            MockGraphRepo.return_value = mock_gr

            from backend.app.graph.services.graph_build_service import GraphBuildService

            svc = GraphBuildService(pg_session=session, neo4j_driver=driver)
            progress = await svc.get_progress(REPO_ID)

        assert progress.total_nodes == 150
        assert progress.total_edges == 420

    @pytest.mark.asyncio
    async def test_raises_when_repo_not_found(self) -> None:
        session = _make_mock_pg_session()
        driver = _make_mock_neo4j()

        with patch(
            "backend.app.graph.services.graph_build_service.RepositoryRepository"
        ) as MockRepoRepo:
            mock_rr = AsyncMock()
            mock_rr.get_by_id.return_value = None
            MockRepoRepo.return_value = mock_rr

            from backend.app.graph.services.graph_build_service import GraphBuildService

            svc = GraphBuildService(pg_session=session, neo4j_driver=driver)
            with pytest.raises(RepositoryNotFoundError):
                await svc.get_progress(REPO_ID)
