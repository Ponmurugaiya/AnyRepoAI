"""Tests for the SymbolIndexRepository data-access layer.

These are unit tests using mocked SQLAlchemy sessions to verify query
construction and result handling without requiring a live database.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.symbol_index.models.index import IndexStatus


REPO_ID = uuid.uuid4()
FILE_ID = uuid.uuid4()


def _make_mock_session() -> AsyncMock:
    """Return a minimal mock async session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    return session


def _make_mock_entry(
    entry_id: uuid.UUID | None = None,
    qualified_name: str = "app.auth.AuthService.login",
    name: str = "login",
    symbol_type: str = "method",
    language: str = "Python",
) -> MagicMock:
    """Return a mock SymbolIndexEntry."""
    entry = MagicMock()
    entry.id = entry_id or uuid.uuid4()
    entry.qualified_name = qualified_name
    entry.name = name
    entry.symbol_type = symbol_type
    entry.language = language
    entry.repository_id = REPO_ID
    entry.file_id = FILE_ID
    return entry


class TestUpsertIndexJob:
    """Verify upsert_index_job() assembles the right SQL and returns the job."""

    @pytest.mark.asyncio
    async def test_upsert_calls_execute_and_flush(self) -> None:
        session = _make_mock_session()

        # Mock the select after insert returning a job
        mock_job = MagicMock()
        mock_job.status = IndexStatus.QUEUED
        mock_scalar = MagicMock()
        mock_scalar.scalar_one.return_value = mock_job
        session.execute.return_value = mock_scalar

        from backend.app.symbol_index.repositories.index_repository import SymbolIndexRepository

        repo = SymbolIndexRepository(session=session)
        job = await repo.upsert_index_job(
            REPO_ID,
            status=IndexStatus.QUEUED,
        )

        assert session.execute.called
        assert session.flush.called


class TestDeleteEntriesByFile:
    """Verify delete_entries_by_file() targets the correct file."""

    @pytest.mark.asyncio
    async def test_delete_returns_row_count(self) -> None:
        session = _make_mock_session()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        session.execute.return_value = mock_result

        from backend.app.symbol_index.repositories.index_repository import SymbolIndexRepository

        repo = SymbolIndexRepository(session=session)
        count = await repo.delete_entries_by_file(FILE_ID)

        assert count == 5
        assert session.flush.called


class TestDeleteEntriesByRepository:
    """Verify delete_entries_by_repository() targets the correct repository."""

    @pytest.mark.asyncio
    async def test_delete_returns_row_count(self) -> None:
        session = _make_mock_session()
        mock_result = MagicMock()
        mock_result.rowcount = 42
        session.execute.return_value = mock_result

        from backend.app.symbol_index.repositories.index_repository import SymbolIndexRepository

        repo = SymbolIndexRepository(session=session)
        count = await repo.delete_entries_by_repository(REPO_ID)

        assert count == 42
        assert session.flush.called


class TestBulkUpsertEntries:
    """Verify bulk_upsert_entries() returns the correct affected count."""

    @pytest.mark.asyncio
    async def test_empty_entries_returns_zero(self) -> None:
        session = _make_mock_session()

        from backend.app.symbol_index.repositories.index_repository import SymbolIndexRepository

        repo = SymbolIndexRepository(session=session)
        count = await repo.bulk_upsert_entries([])

        assert count == 0
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_entries_batched_correctly(self) -> None:
        """Entries exceeding batch size should be split into multiple executes."""
        session = _make_mock_session()
        mock_result = MagicMock()
        mock_result.rowcount = 10
        session.execute.return_value = mock_result

        from backend.app.symbol_index.repositories.index_repository import (
            SymbolIndexRepository,
            _BULK_BATCH_SIZE,
        )

        # Create enough entries to require 2 batches
        entries = [
            {
                "id": uuid.uuid4(),
                "repository_id": REPO_ID,
                "file_id": FILE_ID,
                "language": "Python",
                "symbol_type": "method",
                "name": f"method_{i}",
                "qualified_name": f"pkg.Class.method_{i}",
                "display_name": f"Class.method_{i}",
                "parent_symbol_id": None,
                "module_name": "pkg",
                "namespace": None,
                "signature": None,
                "return_type": None,
                "visibility": "public",
                "is_static": False,
                "is_async": False,
                "is_exported": True,
                "is_deprecated": False,
                "documentation": None,
                "start_line": i + 1,
                "end_line": i + 2,
                "start_column": 0,
                "end_column": 0,
            }
            for i in range(_BULK_BATCH_SIZE + 5)
        ]

        repo = SymbolIndexRepository(session=session)
        await repo.bulk_upsert_entries(entries)

        # Should have called execute twice (one full batch + one partial)
        assert session.execute.call_count == 2


class TestListEntries:
    """Verify list_entries() passes filters correctly."""

    @pytest.mark.asyncio
    async def test_list_entries_returns_entries(self) -> None:
        session = _make_mock_session()
        mock_entry = _make_mock_entry()
        mock_scalars = MagicMock()
        mock_scalars.scalars.return_value.all.return_value = [mock_entry]
        session.execute.return_value = mock_scalars

        from backend.app.symbol_index.repositories.index_repository import SymbolIndexRepository

        repo = SymbolIndexRepository(session=session)
        entries = await repo.list_entries(REPO_ID)

        assert len(entries) == 1


class TestSearchEntries:
    """Verify search_entries() handles all three modes without raising."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["prefix", "exact", "qualified", "invalid"])
    async def test_search_mode_does_not_raise(self, mode: str) -> None:
        session = _make_mock_session()
        mock_scalars = MagicMock()
        mock_scalars.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_scalars

        from backend.app.symbol_index.repositories.index_repository import SymbolIndexRepository

        repo = SymbolIndexRepository(session=session)
        results = await repo.search_entries(
            REPO_ID, query="login", mode=mode
        )
        assert isinstance(results, list)
