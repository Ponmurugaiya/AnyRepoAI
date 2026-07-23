"""Integration tests for the Symbol Intelligence Engine API endpoints.

Tests all four REST endpoints:
    POST  /repositories/{id}/symbols/index
    GET   /repositories/{id}/symbols/index/progress
    GET   /repositories/{id}/symbols/index/entries
    GET   /repositories/{id}/symbols/index/entries/{symbol_id}
    GET   /repositories/{id}/symbols/index/search

Uses the HTTPX test client provided by the root conftest and mocks the
service/repository layers to avoid requiring a live database.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from backend.app.core.exceptions import RepositoryNotFoundError
from backend.app.symbol_index.models.index import IndexStatus
from backend.app.symbol_index.schemas.index import (
    IndexInitiatedResponse,
    IndexProgressResponse,
    SymbolIndexEntryResponse,
    SymbolIndexListResponse,
    SymbolIndexSearchResponse,
)

REPO_ID = uuid.uuid4()
SYMBOL_ID = uuid.uuid4()


def _make_entry_response(**overrides) -> dict:
    """Return a dict that validates as SymbolIndexEntryResponse."""
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    base = {
        "id": str(SYMBOL_ID),
        "repository_id": str(REPO_ID),
        "file_id": str(uuid.uuid4()),
        "language": "Python",
        "symbol_type": "method",
        "name": "login",
        "qualified_name": "app.auth.AuthService.login",
        "display_name": "AuthService.login",
        "parent_symbol_id": None,
        "module_name": "app.auth",
        "namespace": None,
        "signature": "def login(self) -> Token",
        "return_type": "Token",
        "visibility": "public",
        "is_static": False,
        "is_async": False,
        "is_exported": True,
        "is_deprecated": False,
        "documentation": "Authenticate the user.",
        "start_line": 10,
        "end_line": 25,
        "start_column": 0,
        "end_column": 0,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    base.update(overrides)
    return base


# All API tests mock at the router level to avoid infrastructure setup
_ROUTER_PATH = "backend.app.symbol_index.api.router"


class TestStartSymbolIndex:
    """POST /repositories/{id}/symbols/index"""

    @pytest.mark.asyncio
    async def test_returns_202_accepted(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}._enqueue_index"):
            response = await client.post(
                f"/api/v1/repositories/{REPO_ID}/symbols/index"
            )
        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_response_envelope_structure(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}._enqueue_index"):
            response = await client.post(
                f"/api/v1/repositories/{REPO_ID}/symbols/index"
            )
        body = response.json()
        assert body["success"] is True
        assert body["data"]["status"] == "QUEUED"
        assert str(REPO_ID) in body["data"]["repository_id"]

    @pytest.mark.asyncio
    async def test_dispatches_celery_task(self, client: AsyncClient) -> None:
        with patch(f"{_ROUTER_PATH}._enqueue_index") as mock_enqueue:
            await client.post(
                f"/api/v1/repositories/{REPO_ID}/symbols/index"
            )
        mock_enqueue.assert_called_once()


class TestGetIndexProgress:
    """GET /repositories/{id}/symbols/index/progress"""

    @pytest.mark.asyncio
    async def test_returns_200_with_progress(self, client: AsyncClient) -> None:
        progress = IndexProgressResponse(
            repository_id=REPO_ID,
            status="COMPLETED",
            total_files=50,
            indexed_files=50,
            failed_files=0,
            total_symbols=1200,
            duplicate_symbols=5,
            index_duration_seconds=8.2,
        )
        with patch(
            f"{_ROUTER_PATH}.SymbolIndexService"
        ) as MockService:
            mock_svc = AsyncMock()
            mock_svc.get_progress.return_value = progress
            MockService.return_value = mock_svc

            response = await client.get(
                f"/api/v1/repositories/{REPO_ID}/symbols/index/progress"
            )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["status"] == "COMPLETED"
        assert body["data"]["total_symbols"] == 1200

    @pytest.mark.asyncio
    async def test_404_when_repo_not_found(self, client: AsyncClient) -> None:
        with patch(
            f"{_ROUTER_PATH}.SymbolIndexService"
        ) as MockService:
            mock_svc = AsyncMock()
            mock_svc.get_progress.side_effect = RepositoryNotFoundError(str(REPO_ID))
            MockService.return_value = mock_svc

            response = await client.get(
                f"/api/v1/repositories/{REPO_ID}/symbols/index/progress"
            )

        assert response.status_code == 404


class TestListIndexEntries:
    """GET /repositories/{id}/symbols/index/entries"""

    @pytest.mark.asyncio
    async def test_returns_200_with_entries(self, client: AsyncClient) -> None:
        mock_entry = MagicMock()
        mock_entry.id = SYMBOL_ID
        mock_entry.repository_id = REPO_ID
        mock_entry.file_id = uuid.uuid4()
        mock_entry.language = "Python"
        mock_entry.symbol_type = "method"
        mock_entry.name = "login"
        mock_entry.qualified_name = "app.auth.AuthService.login"
        mock_entry.display_name = "AuthService.login"
        mock_entry.parent_symbol_id = None
        mock_entry.module_name = "app.auth"
        mock_entry.namespace = None
        mock_entry.signature = "def login(self) -> Token"
        mock_entry.return_type = "Token"
        mock_entry.visibility = "public"
        mock_entry.is_static = False
        mock_entry.is_async = False
        mock_entry.is_exported = True
        mock_entry.is_deprecated = False
        mock_entry.documentation = None
        mock_entry.start_line = 10
        mock_entry.end_line = 25
        mock_entry.start_column = 0
        mock_entry.end_column = 0
        import datetime
        mock_entry.created_at = datetime.datetime.now(datetime.timezone.utc)
        mock_entry.updated_at = datetime.datetime.now(datetime.timezone.utc)

        with patch(
            f"{_ROUTER_PATH}.SymbolIndexRepository"
        ) as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.list_entries.return_value = [mock_entry]
            mock_repo.count_entries.return_value = 1
            MockRepo.return_value = mock_repo

            response = await client.get(
                f"/api/v1/repositories/{REPO_ID}/symbols/index/entries"
            )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["total"] == 1
        assert len(body["data"]["items"]) == 1

    @pytest.mark.asyncio
    async def test_filters_accepted(self, client: AsyncClient) -> None:
        with patch(
            f"{_ROUTER_PATH}.SymbolIndexRepository"
        ) as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.list_entries.return_value = []
            mock_repo.count_entries.return_value = 0
            MockRepo.return_value = mock_repo

            response = await client.get(
                f"/api/v1/repositories/{REPO_ID}/symbols/index/entries",
                params={
                    "language": "Python",
                    "symbol_type": "method",
                    "limit": "50",
                    "offset": "0",
                },
            )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_pagination_params_validated(self, client: AsyncClient) -> None:
        """limit < 1 should return 422."""
        response = await client.get(
            f"/api/v1/repositories/{REPO_ID}/symbols/index/entries",
            params={"limit": "0"},
        )
        assert response.status_code == 422


class TestGetIndexEntry:
    """GET /repositories/{id}/symbols/index/entries/{symbol_id}"""

    @pytest.mark.asyncio
    async def test_returns_entry_by_id(self, client: AsyncClient) -> None:
        mock_entry = MagicMock()
        mock_entry.id = SYMBOL_ID
        mock_entry.repository_id = REPO_ID
        mock_entry.file_id = uuid.uuid4()
        mock_entry.language = "Python"
        mock_entry.symbol_type = "method"
        mock_entry.name = "login"
        mock_entry.qualified_name = "app.auth.AuthService.login"
        mock_entry.display_name = "AuthService.login"
        mock_entry.parent_symbol_id = None
        mock_entry.module_name = "app.auth"
        mock_entry.namespace = None
        mock_entry.signature = None
        mock_entry.return_type = None
        mock_entry.visibility = "public"
        mock_entry.is_static = False
        mock_entry.is_async = False
        mock_entry.is_exported = True
        mock_entry.is_deprecated = False
        mock_entry.documentation = None
        mock_entry.start_line = 10
        mock_entry.end_line = 25
        mock_entry.start_column = 0
        mock_entry.end_column = 0
        import datetime
        mock_entry.created_at = datetime.datetime.now(datetime.timezone.utc)
        mock_entry.updated_at = datetime.datetime.now(datetime.timezone.utc)

        with patch(
            f"{_ROUTER_PATH}.SymbolIndexRepository"
        ) as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.get_entry_by_id.return_value = mock_entry
            MockRepo.return_value = mock_repo

            response = await client.get(
                f"/api/v1/repositories/{REPO_ID}/symbols/index/entries/{SYMBOL_ID}"
            )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["name"] == "login"

    @pytest.mark.asyncio
    async def test_404_when_entry_not_found(self, client: AsyncClient) -> None:
        with patch(
            f"{_ROUTER_PATH}.SymbolIndexRepository"
        ) as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.get_entry_by_id.return_value = None
            MockRepo.return_value = mock_repo

            response = await client.get(
                f"/api/v1/repositories/{REPO_ID}/symbols/index/entries/{SYMBOL_ID}"
            )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_404_when_entry_belongs_to_different_repo(
        self, client: AsyncClient
    ) -> None:
        other_repo_id = uuid.uuid4()
        mock_entry = MagicMock()
        mock_entry.id = SYMBOL_ID
        mock_entry.repository_id = other_repo_id  # different repo

        with patch(
            f"{_ROUTER_PATH}.SymbolIndexRepository"
        ) as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.get_entry_by_id.return_value = mock_entry
            MockRepo.return_value = mock_repo

            response = await client.get(
                f"/api/v1/repositories/{REPO_ID}/symbols/index/entries/{SYMBOL_ID}"
            )

        assert response.status_code == 404


class TestSearchIndexEntries:
    """GET /repositories/{id}/symbols/index/search"""

    @pytest.mark.asyncio
    async def test_returns_search_results(self, client: AsyncClient) -> None:
        with patch(
            f"{_ROUTER_PATH}.SymbolIndexRepository"
        ) as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.search_entries.return_value = []
            MockRepo.return_value = mock_repo

            response = await client.get(
                f"/api/v1/repositories/{REPO_ID}/symbols/index/search",
                params={"q": "login"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["query"] == "login"
        assert body["data"]["total"] == 0

    @pytest.mark.asyncio
    async def test_query_param_required(self, client: AsyncClient) -> None:
        """Missing q parameter should return 422."""
        response = await client.get(
            f"/api/v1/repositories/{REPO_ID}/symbols/index/search"
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["prefix", "exact", "qualified"])
    async def test_all_search_modes_accepted(
        self, client: AsyncClient, mode: str
    ) -> None:
        with patch(
            f"{_ROUTER_PATH}.SymbolIndexRepository"
        ) as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.search_entries.return_value = []
            MockRepo.return_value = mock_repo

            response = await client.get(
                f"/api/v1/repositories/{REPO_ID}/symbols/index/search",
                params={"q": "test", "mode": mode},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["mode"] == mode

    @pytest.mark.asyncio
    async def test_invalid_mode_coerced_to_prefix(
        self, client: AsyncClient
    ) -> None:
        with patch(
            f"{_ROUTER_PATH}.SymbolIndexRepository"
        ) as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.search_entries.return_value = []
            MockRepo.return_value = mock_repo

            response = await client.get(
                f"/api/v1/repositories/{REPO_ID}/symbols/index/search",
                params={"q": "test", "mode": "fuzzy"},
            )

        assert response.status_code == 200
        # mode coerced to "prefix"
        assert response.json()["data"]["mode"] == "prefix"

    @pytest.mark.asyncio
    async def test_empty_query_rejected(self, client: AsyncClient) -> None:
        """Empty q string should fail validation."""
        response = await client.get(
            f"/api/v1/repositories/{REPO_ID}/symbols/index/search",
            params={"q": ""},
        )
        assert response.status_code == 422
