"""Pytest configuration for Knowledge Graph tests.

Provides a self-contained FastAPI test client that mounts ONLY the graph
router.  Two broken-environment stubs must be installed before any
application module is imported:

1. ``neo4j`` — importing it triggers pandas → numpy binary incompatibility
   on this Python 3.10 environment.  We replace the entire package with a
   minimal MagicMock stub.
2. ``backend.app.dependencies`` — eagerly imports neo4j/qdrant clients via
   ``infrastructure.py``; replaced with a stub that provides only ``get_db``
   and a proper ``DBSession`` Annotated type so FastAPI resolves dependencies.

All graph repository / service calls are patched per-test with unittest.mock.
"""

from __future__ import annotations

import sys
import types
from collections.abc import AsyncGenerator
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock

import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


# ── Noop DB session ────────────────────────────────────────────────────────────


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


async def _get_db_stub() -> AsyncGenerator[AsyncSession, None]:  # type: ignore[misc]
    """Standalone get_db that never touches any infrastructure."""
    yield _make_noop_session()


# ── Step 1: stub neo4j BEFORE any application module is imported ───────────────


def _install_neo4j_stub() -> None:
    """Replace the neo4j package with a minimal stub.

    The real neo4j package triggers ``import pandas`` at module load time,
    which crashes with a numpy binary incompatibility on Python 3.10 in
    this environment.  The stub satisfies all type annotations used by
    ``graph_repository.py`` and ``neo4j_client.py``.
    """
    if "neo4j" in sys.modules:
        return

    neo4j_stub = types.ModuleType("neo4j")
    neo4j_stub.AsyncDriver = MagicMock  # type: ignore[attr-defined]
    neo4j_stub.AsyncGraphDatabase = MagicMock()  # type: ignore[attr-defined]
    neo4j_stub.AsyncSession = MagicMock  # type: ignore[attr-defined]

    exc_stub = types.ModuleType("neo4j.exceptions")
    exc_stub.ServiceUnavailable = Exception  # type: ignore[attr-defined]
    exc_stub.AuthError = Exception  # type: ignore[attr-defined]
    exc_stub.TransientError = Exception  # type: ignore[attr-defined]

    sys.modules["neo4j"] = neo4j_stub
    sys.modules["neo4j.exceptions"] = exc_stub


# ── Step 2: stub backend.app.dependencies BEFORE router import ────────────────


def _install_dependency_stubs() -> None:
    """Replace the dependencies package with lightweight stubs."""
    pkg = "backend.app.dependencies"
    db_pkg = "backend.app.dependencies.database"
    infra_pkg = "backend.app.dependencies.infrastructure"

    if pkg not in sys.modules:
        stub = types.ModuleType(pkg)
        stub.get_db = _get_db_stub  # type: ignore[attr-defined]
        stub.get_redis_client = MagicMock()  # type: ignore[attr-defined]
        stub.get_qdrant_client = MagicMock()  # type: ignore[attr-defined]
        stub.get_neo4j_driver = MagicMock()  # type: ignore[attr-defined]
        sys.modules[pkg] = stub

    if db_pkg not in sys.modules:
        db_stub = types.ModuleType(db_pkg)
        db_stub.get_db = _get_db_stub  # type: ignore[attr-defined]
        # Must be a real Annotated[...] so FastAPI injects it, not treats it
        # as a query parameter.
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


# Install both stubs at module import time — must happen before any app import.
_install_neo4j_stub()
_install_dependency_stubs()


# ── Build the minimal test app (runs once at module import) ───────────────────


def _build_test_app() -> FastAPI:
    """Build a FastAPI app with only the graph router and exception handlers."""
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from backend.app.api.exception_handlers import (
        app_exception_handler,
        http_exception_handler,
        unhandled_exception_handler,
        validation_exception_handler,
    )
    from backend.app.core.exceptions import AppException
    from backend.app.graph.api.router import router as graph_router

    app = FastAPI(title="Graph Test App")
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(graph_router, prefix="/api/v1")
    app.dependency_overrides[_get_db_stub] = _get_db_stub
    return app


_TEST_APP = _build_test_app()


# ── Per-test async client fixture ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Yield an HTTPX async client bound to the minimal graph test app."""

    async def _noop_db() -> AsyncGenerator[AsyncSession, None]:
        yield _make_noop_session()

    _TEST_APP.dependency_overrides[_get_db_stub] = _noop_db

    async with AsyncClient(
        transport=ASGITransport(app=_TEST_APP),
        base_url="http://test",
    ) as ac:
        yield ac

    _TEST_APP.dependency_overrides[_get_db_stub] = _noop_db
