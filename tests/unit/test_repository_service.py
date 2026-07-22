"""Unit tests for RepositoryService.

All external I/O (database, GitHub API, git clone) is mocked so these
tests run without any infrastructure dependencies.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.core.exceptions import (
    RepositoryAlreadyExistsError,
    RepositoryNotFoundError,
)
from backend.app.infrastructure.github_client import GitHubRepoMetadata
from backend.app.infrastructure.git_client import CloneResult
from backend.app.models.repository import Repository, RepositoryStatus
from backend.app.schemas.repository import RepositoryCreateRequest
from backend.app.services.repository_service import RepositoryService


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_repo(
    *,
    full_name: str = "octocat/hello",
    status: RepositoryStatus = RepositoryStatus.PENDING,
    local_path: str | None = None,
) -> Repository:
    """Build a mock Repository ORM instance."""
    repo = MagicMock(spec=Repository)
    repo.id = uuid.uuid4()
    repo.owner = full_name.split("/")[0]
    repo.name = full_name.split("/")[1]
    repo.full_name = full_name
    repo.github_url = f"https://github.com/{full_name}"
    repo.clone_status = status
    repo.local_path = local_path
    return repo


def _make_github_meta(full_name: str = "octocat/hello") -> GitHubRepoMetadata:
    owner, name = full_name.split("/")
    return GitHubRepoMetadata(
        name=name,
        owner=owner,
        full_name=full_name,
        description="Test repo",
        default_branch="main",
        visibility="public",
        language="Python",
        stars=10,
        forks=2,
        private=False,
        clone_url=f"https://github.com/{full_name}.git",
    )


# ── create_repository ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_repository_new_url_returns_pending():
    """A fresh URL should create a PENDING record and return its id."""
    session = AsyncMock()
    repo_repo = AsyncMock()
    new_repo = _make_repo()
    repo_repo.get_by_github_url.return_value = None
    repo_repo.create.return_value = new_repo

    github_client = AsyncMock()

    with patch(
        "backend.app.services.repository_service.RepositoryRepository",
        return_value=repo_repo,
    ):
        service = RepositoryService(session=session, github_client=github_client)
        request = RepositoryCreateRequest(github_url="https://github.com/octocat/hello")
        result = await service.create_repository(request)

    assert result.id == new_repo.id
    assert result.status == RepositoryStatus.PENDING
    repo_repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_repository_duplicate_raises_conflict():
    """Duplicate URL without reclone=True must raise RepositoryAlreadyExistsError."""
    session = AsyncMock()
    repo_repo = AsyncMock()
    existing = _make_repo(status=RepositoryStatus.READY)
    repo_repo.get_by_github_url.return_value = existing

    with patch(
        "backend.app.services.repository_service.RepositoryRepository",
        return_value=repo_repo,
    ):
        service = RepositoryService(session=session, github_client=AsyncMock())
        request = RepositoryCreateRequest(github_url="https://github.com/octocat/hello")

        with pytest.raises(RepositoryAlreadyExistsError):
            await service.create_repository(request)


@pytest.mark.asyncio
async def test_create_repository_reclone_resets_existing():
    """reclone=True must reset existing repo to PENDING and remove old clone."""
    session = AsyncMock()
    repo_repo = AsyncMock()
    existing = _make_repo(status=RepositoryStatus.READY, local_path="/storage/repos/abc")
    repo_repo.get_by_github_url.return_value = existing
    repo_repo.update_status.return_value = existing

    with (
        patch(
            "backend.app.services.repository_service.RepositoryRepository",
            return_value=repo_repo,
        ),
        patch(
            "backend.app.services.repository_service.remove_clone",
            new_callable=AsyncMock,
        ) as mock_remove,
    ):
        service = RepositoryService(session=session, github_client=AsyncMock())
        request = RepositoryCreateRequest(
            github_url="https://github.com/octocat/hello", reclone=True
        )
        result = await service.create_repository(request)

    mock_remove.assert_awaited_once_with("/storage/repos/abc")
    repo_repo.update_status.assert_awaited_once_with(existing, RepositoryStatus.PENDING)
    assert result.status == RepositoryStatus.PENDING


# ── get_repository ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_repository_not_found_raises():
    """get_repository with unknown UUID must raise RepositoryNotFoundError."""
    session = AsyncMock()
    repo_repo = AsyncMock()
    repo_repo.get_by_id.return_value = None

    with patch(
        "backend.app.services.repository_service.RepositoryRepository",
        return_value=repo_repo,
    ):
        service = RepositoryService(session=session, github_client=AsyncMock())
        with pytest.raises(RepositoryNotFoundError):
            await service.get_repository(uuid.uuid4())


@pytest.mark.asyncio
async def test_get_repository_returns_response():
    """get_repository should map ORM model to RepositoryResponse."""
    session = AsyncMock()
    repo_repo = AsyncMock()

    # Build a realistic ORM-like mock
    repo = MagicMock(spec=Repository)
    repo.id = uuid.uuid4()
    repo.owner = "octocat"
    repo.name = "hello"
    repo.full_name = "octocat/hello"
    repo.github_url = "https://github.com/octocat/hello"
    repo.default_branch = "main"
    repo.local_path = "/storage/repos/some-id"
    repo.current_commit = "abc123"
    repo.description = "A repo"
    repo.visibility = "public"
    repo.language = "Python"
    repo.stars = 5
    repo.forks = 1
    repo.clone_status = RepositoryStatus.READY
    repo.created_at = datetime.now(timezone.utc)
    repo.updated_at = datetime.now(timezone.utc)
    repo.last_synced_at = None
    repo_repo.get_by_id.return_value = repo

    with patch(
        "backend.app.services.repository_service.RepositoryRepository",
        return_value=repo_repo,
    ):
        service = RepositoryService(session=session, github_client=AsyncMock())
        response = await service.get_repository(repo.id)

    assert response.full_name == "octocat/hello"
    assert response.clone_status == RepositoryStatus.READY


# ── delete_repository ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_repository_removes_record_and_clone():
    """delete_repository must delete DB record and remove filesystem clone."""
    session = AsyncMock()
    repo_repo = AsyncMock()
    repo = _make_repo(local_path="/storage/repos/my-id")
    repo_repo.get_by_id.return_value = repo

    with (
        patch(
            "backend.app.services.repository_service.RepositoryRepository",
            return_value=repo_repo,
        ),
        patch(
            "backend.app.services.repository_service.remove_clone",
            new_callable=AsyncMock,
        ) as mock_remove,
    ):
        service = RepositoryService(session=session, github_client=AsyncMock())
        await service.delete_repository(repo.id)

    repo_repo.delete.assert_awaited_once_with(repo)
    mock_remove.assert_awaited_once_with("/storage/repos/my-id")


@pytest.mark.asyncio
async def test_delete_repository_not_found_raises():
    """delete_repository with unknown UUID must raise RepositoryNotFoundError."""
    session = AsyncMock()
    repo_repo = AsyncMock()
    repo_repo.get_by_id.return_value = None

    with patch(
        "backend.app.services.repository_service.RepositoryRepository",
        return_value=repo_repo,
    ):
        service = RepositoryService(session=session, github_client=AsyncMock())
        with pytest.raises(RepositoryNotFoundError):
            await service.delete_repository(uuid.uuid4())


# ── list_repositories ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_repositories_returns_all():
    """list_repositories should return all ORM records mapped to RepositoryResponse."""
    session = AsyncMock()
    repo_repo = AsyncMock()

    repos = []
    for i in range(3):
        r = MagicMock(spec=Repository)
        r.id = uuid.uuid4()
        r.owner = "org"
        r.name = f"repo-{i}"
        r.full_name = f"org/repo-{i}"
        r.github_url = f"https://github.com/org/repo-{i}"
        r.default_branch = "main"
        r.local_path = None
        r.current_commit = None
        r.description = None
        r.visibility = "public"
        r.language = None
        r.stars = 0
        r.forks = 0
        r.clone_status = RepositoryStatus.PENDING
        r.created_at = datetime.now(timezone.utc)
        r.updated_at = datetime.now(timezone.utc)
        r.last_synced_at = None
        repos.append(r)

    repo_repo.list_all.return_value = repos

    with patch(
        "backend.app.services.repository_service.RepositoryRepository",
        return_value=repo_repo,
    ):
        service = RepositoryService(session=session, github_client=AsyncMock())
        result = await service.list_repositories()

    assert result.total == 3
    assert len(result.items) == 3
