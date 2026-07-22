"""Pytest configuration and shared fixtures.

Sets up an in-memory-style test database using the application's
async SQLAlchemy engine, and provides a test FastAPI client.
"""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.dependencies.database import get_db
from backend.app.infrastructure.github_client import GitHubRepoMetadata
from backend.app.main import create_application

# ── Test database ──────────────────────────────────────────────────────────────
# Use a real (but test-isolated) PostgreSQL URL, falling back to SQLite for
# environments without Postgres.  The fixture drops and recreates all tables
# before every test session.

_TEST_DB_URL = (
    get_settings().database.async_url.replace(
        get_settings().database.db, f"{get_settings().database.db}_test"
    )
)


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create the test database engine and initialise the schema."""
    _engine = create_async_engine(
        _TEST_DB_URL,
        echo=False,
        poolclass=StaticPool,
    )
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield _engine

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield a transactional test session that rolls back after each test."""
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Yield an HTTPX async client bound to the test app.

    Overrides the ``get_db`` dependency so all requests use the
    transactional test session that rolls back after each test.
    """
    app = create_application()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ── GitHub client mock ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_github_metadata() -> GitHubRepoMetadata:
    """Return a canned :class:`GitHubRepoMetadata` for unit tests."""
    return GitHubRepoMetadata(
        name="my-repo",
        owner="octocat",
        full_name="octocat/my-repo",
        description="A test repository",
        default_branch="main",
        visibility="public",
        language="Python",
        stars=42,
        forks=7,
        private=False,
        clone_url="https://github.com/octocat/my-repo.git",
    )


@pytest.fixture
def mock_github_client(mock_github_metadata: GitHubRepoMetadata) -> AsyncMock:
    """Return an AsyncMock that replaces :class:`GitHubClient` in service tests."""
    client = AsyncMock()
    client.get_repository.return_value = mock_github_metadata
    return client
