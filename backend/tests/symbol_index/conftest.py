"""Pytest configuration for Symbol Intelligence Engine tests.

Provides a self-contained FastAPI test client that mounts ONLY the
symbol_index router. This sidesteps two environment-specific problems:

1. ``health.py`` uses ``datetime.UTC`` which requires Python 3.11+.
2. ``backend.app.dependencies.__init__`` eagerly imports neo4j, which
   pulls in pandas, and that pandas build has a numpy binary incompatibility
   on this Python 3.10 environment.

The workaround: inject stub modules for the entire ``dependencies``
package into ``sys.modules`` *before* any app code is imported. This
prevents neo4j from ever loading. All repository / service calls are
patched per-test with unittest.mock.
"""

from __future__ import annotations

import sys
import types
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


# ── Minimal async session mock ─────────────────────────────────────────────────


def _make_noop_session() -> AsyncSession:
    """Return an AsyncMock that behaves like an idle AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    empty = MagicMock()
    empty.scalar_one_or_none.return_value = None
    empty.scalar_one.return_value = 0
    empty.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=empty)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session  # type: ignore[return-value]


# ── Stub the broken dependencies package before any router import ──────────────


async def _get_db_stub() -> AsyncGenerator[AsyncSession, None]:  # type: ignore[misc]
    """Standalone get_db callable that never touches neo4j or qdrant."""
    yield _make_noop_session()


def _install_dependency_stubs() -> None:
    """Pre-populate sys.modules with lightweight stubs for dependencies.

    Called at conftest import time.  Safe to call multiple times.
    """
    pkg = "backend.app.dependencies"
    db_pkg = "backend.app.dependencies.database"
    infra_pkg = "backend.app.dependencies.infrastructure"

    # Only install if not yet present — don't clobber a successful real load.
    if pkg not in sys.modules:
        stub = types.ModuleType(pkg)
        stub.get_db = _get_db_stub  # type: ignore[attr-defined]
        stub.get_redis_client = MagicMock()  # type: ignore[attr-defined]
        stub.get_qdrant_client = MagicMock()  # type: ignore[attr-defined]
        stub.get_neo4j_driver = MagicMock()  # type: ignore[attr-defined]
        sys.modules[pkg] = stub

    if db_pkg not in sys.modules:
        from typing import Annotated
        from fastapi import Depends

        db_stub = types.ModuleType(db_pkg)
        db_stub.get_db = _get_db_stub  # type: ignore[attr-defined]
        # Must be a real Annotated[AsyncSession, Depends(get_db)] so FastAPI
        # recognises it as an injected dependency, not a query parameter.
        db_stub.DBSession = Annotated[AsyncSession, Depends(_get_db_stub)]  # type: ignore[attr-defined]
        sys.modules[db_pkg] = db_stub

    if infra_pkg not in sys.modules:
        infra_stub = types.ModuleType(infra_pkg)
        infra_stub.get_redis_client = MagicMock()  # type: ignore[attr-defined]
        infra_stub.get_qdrant_client = MagicMock()  # type: ignore[attr-defined]
        infra_stub.get_neo4j_driver = MagicMock()  # type: ignore[attr-defined]
        infra_stub.RedisClient = None  # type: ignore[attr-defined]
        infra_stub.QdrantClientDep = None  # type: ignore[attr-defined]
        infra_stub.Neo4jDriverDep = None  # type: ignore[attr-defined]
        sys.modules[infra_pkg] = infra_stub


_install_dependency_stubs()


# ── Build the minimal test app (runs once at module import time) ───────────────


def _build_test_app() -> FastAPI:
    """Build a FastAPI app containing only the symbol_index router.

    All imports happen here, after the dependency stubs are installed,
    so neo4j/pandas are never loaded.
    """
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from backend.app.api.exception_handlers import (
        app_exception_handler,
        http_exception_handler,
        unhandled_exception_handler,
        validation_exception_handler,
    )
    from backend.app.core.exceptions import AppException
    from backend.app.symbol_index.api.router import router as symbol_index_router

    app = FastAPI(title="Symbol Index Test App")
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(symbol_index_router, prefix="/api/v1")
    app.dependency_overrides[_get_db_stub] = _get_db_stub
    return app


_TEST_APP = _build_test_app()


# ── Per-test async client fixture ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Yield an HTTPX async client bound to the minimal symbol-index test app.

    The dependency_overrides dict is reset after each test so patches
    from one test cannot bleed into the next.
    """
    # Fresh noop session for each test
    async def _noop_db() -> AsyncGenerator[AsyncSession, None]:
        yield _make_noop_session()

    _TEST_APP.dependency_overrides[_get_db_stub] = _noop_db

    async with AsyncClient(
        transport=ASGITransport(app=_TEST_APP),
        base_url="http://test",
    ) as ac:
        yield ac

    _TEST_APP.dependency_overrides[_get_db_stub] = _noop_db
