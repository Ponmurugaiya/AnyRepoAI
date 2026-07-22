"""Unit tests for the GitHubClient metadata extraction.

Uses respx (or httpx mock) to intercept HTTP calls without hitting
the real GitHub API.
"""

import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from backend.app.core.exceptions import ExternalServiceError, RepositoryAccessError
from backend.app.infrastructure.github_client import GitHubClient


# ── Helpers ────────────────────────────────────────────────────────────────────

_SAMPLE_API_RESPONSE = {
    "name": "hello-world",
    "owner": {"login": "octocat"},
    "full_name": "octocat/hello-world",
    "description": "My first repository on GitHub!",
    "default_branch": "main",
    "visibility": "public",
    "language": "Python",
    "stargazers_count": 1500,
    "forks_count": 200,
    "private": False,
    "clone_url": "https://github.com/octocat/hello-world.git",
}


@pytest.fixture
def github_client() -> GitHubClient:
    """Return a GitHubClient with a mocked httpx transport."""
    return GitHubClient(base_url="https://api.github.com", token=None, timeout=5.0)


@pytest.mark.asyncio
async def test_get_repository_success(github_client: GitHubClient) -> None:
    """Successful 200 response should map to GitHubRepoMetadata."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _SAMPLE_API_RESPONSE

    github_client._client.get = AsyncMock(return_value=mock_response)

    meta = await github_client.get_repository("octocat", "hello-world")

    assert meta.name == "hello-world"
    assert meta.owner == "octocat"
    assert meta.full_name == "octocat/hello-world"
    assert meta.stars == 1500
    assert meta.forks == 200
    assert meta.default_branch == "main"
    assert meta.language == "Python"
    assert meta.visibility == "public"


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 404])
async def test_get_repository_access_denied_raises(
    github_client: GitHubClient, status_code: int
) -> None:
    """401, 403, or 404 from GitHub should raise RepositoryAccessError."""
    mock_response = MagicMock()
    mock_response.status_code = status_code

    github_client._client.get = AsyncMock(return_value=mock_response)

    with pytest.raises(RepositoryAccessError):
        await github_client.get_repository("owner", "private-repo")


@pytest.mark.asyncio
async def test_get_repository_unexpected_status_raises(
    github_client: GitHubClient,
) -> None:
    """A 5xx response should raise ExternalServiceError."""
    mock_response = MagicMock()
    mock_response.status_code = 503
    mock_response.text = "Service Unavailable"

    github_client._client.get = AsyncMock(return_value=mock_response)

    with pytest.raises(ExternalServiceError):
        await github_client.get_repository("owner", "repo")


@pytest.mark.asyncio
async def test_get_repository_timeout_raises(github_client: GitHubClient) -> None:
    """A TimeoutException from httpx should raise ExternalServiceError."""
    github_client._client.get = AsyncMock(
        side_effect=httpx.TimeoutException("timed out")
    )

    with pytest.raises(ExternalServiceError):
        await github_client.get_repository("owner", "repo")
