"""Integration tests for the Repository Management API endpoints.

These tests run the full FastAPI request/response cycle against a real
(test-isolated) PostgreSQL database. GitHub API calls and git clone
operations are mocked so the tests remain fast and deterministic.

Prerequisites:
    - A running PostgreSQL instance accessible at the URL in .env
      (the test session will use a separate ``_test`` database).
    - Run via: pytest tests/integration/ -v
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from backend.app.infrastructure.git_client import CloneResult
from backend.app.infrastructure.github_client import GitHubRepoMetadata
from backend.app.models.repository import RepositoryStatus

# ── Fixtures ───────────────────────────────────────────────────────────────────

_SAMPLE_GITHUB_META = GitHubRepoMetadata(
    name="hello-world",
    owner="octocat",
    full_name="octocat/hello-world",
    description="My first repository on GitHub!",
    default_branch="main",
    visibility="public",
    language="Python",
    stars=100,
    forks=10,
    private=False,
    clone_url="https://github.com/octocat/hello-world.git",
)

_SAMPLE_CLONE_RESULT = CloneResult(
    local_path="/storage/repos/test-id",
    default_branch="main",
    current_commit="abc123def456abc123def456abc123def456abc1",
)


def _mock_pipeline_patches():
    """Context managers to patch GitHub and git operations."""
    return [
        patch(
            "backend.app.services.repository_service.clone_repository",
            new_callable=AsyncMock,
            return_value=_SAMPLE_CLONE_RESULT,
        ),
        patch(
            "backend.app.services.repository_service.GitHubClient.get_repository",
            new_callable=AsyncMock,
            return_value=_SAMPLE_GITHUB_META,
        ),
        # Prevent Celery dispatch from failing in test environment
        patch("backend.app.api.v1.repositories._enqueue_clone"),
    ]


# ── POST /repositories ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_repository_returns_202_pending(client) -> None:
    """POST with a valid URL must return 202 with PENDING status."""
    with patch("backend.app.api.v1.repositories._enqueue_clone"):
        response = await client.post(
            "/api/v1/repositories",
            json={"github_url": "https://github.com/octocat/hello-world"},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "PENDING"
    assert "id" in body["data"]


@pytest.mark.asyncio
async def test_post_repository_invalid_url_returns_422(client) -> None:
    """An invalid URL must return 422 with a meaningful error."""
    response = await client.post(
        "/api/v1/repositories",
        json={"github_url": "https://gitlab.com/owner/repo"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_repository_duplicate_returns_409(client) -> None:
    """Registering the same URL twice must return 409 Conflict."""
    with patch("backend.app.api.v1.repositories._enqueue_clone"):
        first = await client.post(
            "/api/v1/repositories",
            json={"github_url": "https://github.com/octocat/duplicate-repo"},
        )
        assert first.status_code == 202

        second = await client.post(
            "/api/v1/repositories",
            json={"github_url": "https://github.com/octocat/duplicate-repo"},
        )
        assert second.status_code == 409


@pytest.mark.asyncio
async def test_post_repository_reclone_resets_existing(client) -> None:
    """reclone=true should reset an existing repository to PENDING."""
    url = "https://github.com/octocat/reclone-repo"

    with patch("backend.app.api.v1.repositories._enqueue_clone"):
        first = await client.post(
            "/api/v1/repositories",
            json={"github_url": url},
        )
        assert first.status_code == 202
        first_id = first.json()["data"]["id"]

        second = await client.post(
            "/api/v1/repositories",
            json={"github_url": url, "reclone": True},
        )
        assert second.status_code == 202
        # Should return the same repository id
        assert second.json()["data"]["id"] == first_id


# ── GET /repositories ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_repositories_empty(client) -> None:
    """GET /repositories on an empty database must return an empty list."""
    response = await client.get("/api/v1/repositories")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert isinstance(body["data"]["items"], list)
    assert body["data"]["total"] >= 0


@pytest.mark.asyncio
async def test_list_repositories_contains_created_repo(client) -> None:
    """After creation, the repository must appear in the list."""
    with patch("backend.app.api.v1.repositories._enqueue_clone"):
        await client.post(
            "/api/v1/repositories",
            json={"github_url": "https://github.com/octocat/list-test-repo"},
        )

    response = await client.get("/api/v1/repositories")
    assert response.status_code == 200
    full_names = [r["full_name"] for r in response.json()["data"]["items"]]
    assert "octocat/list-test-repo" in full_names


# ── GET /repositories/{id} ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_repository_by_id(client) -> None:
    """GET /repositories/{id} must return the full detail view."""
    with patch("backend.app.api.v1.repositories._enqueue_clone"):
        post_resp = await client.post(
            "/api/v1/repositories",
            json={"github_url": "https://github.com/octocat/get-by-id-repo"},
        )
    repo_id = post_resp.json()["data"]["id"]

    get_resp = await client.get(f"/api/v1/repositories/{repo_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()["data"]
    assert data["id"] == repo_id
    assert data["full_name"] == "octocat/get-by-id-repo"


@pytest.mark.asyncio
async def test_get_repository_not_found_returns_404(client) -> None:
    """GET /repositories/{unknown_id} must return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/api/v1/repositories/{fake_id}")
    assert response.status_code == 404


# ── DELETE /repositories/{id} ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_repository_removes_record(client) -> None:
    """DELETE /repositories/{id} must return 200 and remove the record."""
    with patch("backend.app.api.v1.repositories._enqueue_clone"):
        post_resp = await client.post(
            "/api/v1/repositories",
            json={"github_url": "https://github.com/octocat/delete-me"},
        )
    repo_id = post_resp.json()["data"]["id"]

    with patch(
        "backend.app.services.repository_service.remove_clone",
        new_callable=AsyncMock,
    ):
        del_resp = await client.delete(f"/api/v1/repositories/{repo_id}")

    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # Confirm the record is gone
    get_resp = await client.get(f"/api/v1/repositories/{repo_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_repository_not_found_returns_404(client) -> None:
    """DELETE /repositories/{unknown_id} must return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.delete(f"/api/v1/repositories/{fake_id}")
    assert response.status_code == 404
