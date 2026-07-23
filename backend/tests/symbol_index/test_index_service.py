"""Tests for the SymbolIndexService.

Tests the indexing orchestration layer using real parser output from
the existing parser fixture files, plus mock-heavy unit tests for
edge cases.

All tests that write to the database use in-memory test sessions provided
by the existing conftest fixtures.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from backend.app.core.exceptions import RepositoryNotFoundError, RepositoryNotReadyError
from backend.app.models.file import FileStatus, ProgrammingLanguage
from backend.app.models.repository import RepositoryStatus
from backend.app.symbol_index.schemas.index import IndexStatistics, IndexProgressResponse
from backend.app.symbol_index.models.index import IndexStatus

# ── Fixtures ───────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent.parent / "parsers" / "fixtures"

REPO_ID = uuid.uuid4()
FILE_ID = uuid.uuid4()


def _make_mock_repository(
    *,
    repo_id: uuid.UUID | None = None,
    clone_status: RepositoryStatus = RepositoryStatus.READY,
) -> MagicMock:
    """Return a mock Repository ORM object."""
    repo = MagicMock()
    repo.id = repo_id or REPO_ID
    repo.clone_status = clone_status
    repo.full_name = "owner/test-repo"
    return repo


def _make_mock_file(
    *,
    file_id: uuid.UUID | None = None,
    language: ProgrammingLanguage = ProgrammingLanguage.PYTHON,
    scan_status: FileStatus = FileStatus.SCANNED,
    relative_path: str = "app/auth.py",
    absolute_path: str | None = None,
) -> MagicMock:
    """Return a mock RepositoryFile ORM object."""
    f = MagicMock()
    f.id = file_id or FILE_ID
    f.language = language
    f.scan_status = scan_status
    f.relative_path = relative_path
    f.absolute_path = absolute_path or str(FIXTURE_DIR / "sample_python.py")
    f.is_binary = False
    return f


class TestSymbolIndexServiceProgress:
    """Unit tests for get_progress()."""

    @pytest.mark.asyncio
    async def test_progress_not_started_when_no_job(self) -> None:
        session = AsyncMock()

        with (
            patch(
                "backend.app.symbol_index.services.index_service.RepositoryRepository"
            ) as MockRepoRepo,
            patch(
                "backend.app.symbol_index.services.index_service.SymbolIndexRepository"
            ) as MockIndexRepo,
        ):
            mock_repo_repo = AsyncMock()
            mock_repo_repo.get_by_id.return_value = _make_mock_repository()
            MockRepoRepo.return_value = mock_repo_repo

            mock_index_repo = AsyncMock()
            mock_index_repo.get_index_job.return_value = None
            MockIndexRepo.return_value = mock_index_repo

            from backend.app.symbol_index.services.index_service import SymbolIndexService

            service = SymbolIndexService(session=session)
            progress = await service.get_progress(REPO_ID)

        assert progress.status == "NOT_STARTED"
        assert progress.repository_id == REPO_ID

    @pytest.mark.asyncio
    async def test_progress_raises_when_repo_not_found(self) -> None:
        session = AsyncMock()

        with patch(
            "backend.app.symbol_index.services.index_service.RepositoryRepository"
        ) as MockRepoRepo:
            mock_repo_repo = AsyncMock()
            mock_repo_repo.get_by_id.return_value = None
            MockRepoRepo.return_value = mock_repo_repo

            from backend.app.symbol_index.services.index_service import SymbolIndexService

            service = SymbolIndexService(session=session)
            with pytest.raises(RepositoryNotFoundError):
                await service.get_progress(REPO_ID)

    @pytest.mark.asyncio
    async def test_progress_returns_job_state(self) -> None:
        session = AsyncMock()

        mock_job = MagicMock()
        mock_job.status = IndexStatus.COMPLETED
        mock_job.total_files = 100
        mock_job.indexed_files = 98
        mock_job.failed_files = 2
        mock_job.total_symbols = 1500
        mock_job.duplicate_symbols = 3
        mock_job.index_duration_seconds = 12.5

        with (
            patch(
                "backend.app.symbol_index.services.index_service.RepositoryRepository"
            ) as MockRepoRepo,
            patch(
                "backend.app.symbol_index.services.index_service.SymbolIndexRepository"
            ) as MockIndexRepo,
        ):
            mock_repo_repo = AsyncMock()
            mock_repo_repo.get_by_id.return_value = _make_mock_repository()
            MockRepoRepo.return_value = mock_repo_repo

            mock_index_repo = AsyncMock()
            mock_index_repo.get_index_job.return_value = mock_job
            MockIndexRepo.return_value = mock_index_repo

            from backend.app.symbol_index.services.index_service import SymbolIndexService

            service = SymbolIndexService(session=session)
            progress = await service.get_progress(REPO_ID)

        assert progress.status == "COMPLETED"
        assert progress.total_symbols == 1500
        assert progress.indexed_files == 98
        assert progress.failed_files == 2


class TestSymbolIndexServiceIndexRepository:
    """Unit tests for index_repository() validation paths."""

    @pytest.mark.asyncio
    async def test_raises_when_repo_not_found(self) -> None:
        session = AsyncMock()

        with patch(
            "backend.app.symbol_index.services.index_service.RepositoryRepository"
        ) as MockRepoRepo:
            mock_repo_repo = AsyncMock()
            mock_repo_repo.get_by_id.return_value = None
            MockRepoRepo.return_value = mock_repo_repo

            from backend.app.symbol_index.services.index_service import SymbolIndexService

            service = SymbolIndexService(session=session)
            with pytest.raises(RepositoryNotFoundError):
                await service.index_repository(REPO_ID)

    @pytest.mark.asyncio
    async def test_raises_when_repo_not_ready(self) -> None:
        session = AsyncMock()

        with patch(
            "backend.app.symbol_index.services.index_service.RepositoryRepository"
        ) as MockRepoRepo:
            mock_repo_repo = AsyncMock()
            mock_repo_repo.get_by_id.return_value = _make_mock_repository(
                clone_status=RepositoryStatus.CLONING
            )
            MockRepoRepo.return_value = mock_repo_repo

            from backend.app.symbol_index.services.index_service import SymbolIndexService

            service = SymbolIndexService(session=session)
            with pytest.raises(RepositoryNotReadyError):
                await service.index_repository(REPO_ID)

    @pytest.mark.asyncio
    async def test_returns_empty_stats_when_no_files(self) -> None:
        session = AsyncMock()

        with (
            patch(
                "backend.app.symbol_index.services.index_service.RepositoryRepository"
            ) as MockRepoRepo,
            patch(
                "backend.app.symbol_index.services.index_service.FileRepository"
            ) as MockFileRepo,
            patch(
                "backend.app.symbol_index.services.index_service.SymbolRepository"
            ) as MockSymRepo,
            patch(
                "backend.app.symbol_index.services.index_service.SymbolIndexRepository"
            ) as MockIndexRepo,
        ):
            mock_repo_repo = AsyncMock()
            mock_repo_repo.get_by_id.return_value = _make_mock_repository()
            MockRepoRepo.return_value = mock_repo_repo

            mock_file_repo = AsyncMock()
            mock_file_repo.get_by_repository_id.return_value = []
            MockFileRepo.return_value = mock_file_repo

            MockSymRepo.return_value = AsyncMock()

            mock_index_repo = AsyncMock()
            MockIndexRepo.return_value = mock_index_repo

            from backend.app.symbol_index.services.index_service import SymbolIndexService

            service = SymbolIndexService(session=session)
            stats = await service.index_repository(REPO_ID)

        assert stats.total_files == 0
        assert stats.total_symbols == 0


class TestSymbolIndexServiceWithRealParsers:
    """Integration-style tests using real parser output from fixture files.

    These tests exercise the full mapping pipeline without a real database
    by patching out the repository layer.
    """

    @pytest.mark.asyncio
    async def test_indexes_python_fixture_file(self) -> None:
        """Full pipeline: Python fixture → mapper → stats."""
        fixture_path = FIXTURE_DIR / "sample_python.py"
        if not fixture_path.exists():
            pytest.skip("Python fixture file not found")

        session = AsyncMock()
        mock_file = _make_mock_file(
            relative_path="sample_python.py",
            absolute_path=str(fixture_path),
        )

        with (
            patch(
                "backend.app.symbol_index.services.index_service.RepositoryRepository"
            ) as MockRepoRepo,
            patch(
                "backend.app.symbol_index.services.index_service.FileRepository"
            ) as MockFileRepo,
            patch(
                "backend.app.symbol_index.services.index_service.SymbolRepository"
            ) as MockSymRepo,
            patch(
                "backend.app.symbol_index.services.index_service.SymbolIndexRepository"
            ) as MockIndexRepo,
        ):
            mock_repo_repo = AsyncMock()
            mock_repo_repo.get_by_id.return_value = _make_mock_repository()
            MockRepoRepo.return_value = mock_repo_repo

            mock_file_repo = AsyncMock()
            mock_file_repo.get_by_repository_id.return_value = [mock_file]
            MockFileRepo.return_value = mock_file_repo

            MockSymRepo.return_value = AsyncMock()

            mock_index_repo = AsyncMock()
            mock_index_repo.delete_entries_by_repository = AsyncMock(return_value=0)
            mock_index_repo.upsert_index_job = AsyncMock()
            mock_index_repo.bulk_upsert_entries = AsyncMock(return_value=10)
            MockIndexRepo.return_value = mock_index_repo

            from backend.app.symbol_index.services.index_service import SymbolIndexService

            service = SymbolIndexService(session=session)
            stats = await service.index_repository(REPO_ID)

        assert stats.total_files == 1
        assert stats.indexed_files == 1
        assert stats.failed_files == 0
        assert stats.total_symbols > 0

    @pytest.mark.asyncio
    async def test_indexes_fastapi_fixture_file(self) -> None:
        """Full pipeline: FastAPI route fixture → mapper detects route symbols."""
        fixture_path = FIXTURE_DIR / "sample_fastapi.py"
        if not fixture_path.exists():
            pytest.skip("FastAPI fixture file not found")

        session = AsyncMock()
        mock_file = _make_mock_file(
            relative_path="sample_fastapi.py",
            absolute_path=str(fixture_path),
        )

        with (
            patch(
                "backend.app.symbol_index.services.index_service.RepositoryRepository"
            ) as MockRepoRepo,
            patch(
                "backend.app.symbol_index.services.index_service.FileRepository"
            ) as MockFileRepo,
            patch(
                "backend.app.symbol_index.services.index_service.SymbolRepository"
            ) as MockSymRepo,
            patch(
                "backend.app.symbol_index.services.index_service.SymbolIndexRepository"
            ) as MockIndexRepo,
        ):
            mock_repo_repo = AsyncMock()
            mock_repo_repo.get_by_id.return_value = _make_mock_repository()
            MockRepoRepo.return_value = mock_repo_repo

            mock_file_repo = AsyncMock()
            mock_file_repo.get_by_repository_id.return_value = [mock_file]
            MockFileRepo.return_value = mock_file_repo

            MockSymRepo.return_value = AsyncMock()

            # Capture actual entries passed to bulk_upsert_entries
            captured_entries: list = []

            async def capture_upsert(entries):
                captured_entries.extend(entries)
                return len(entries)

            mock_index_repo = AsyncMock()
            mock_index_repo.delete_entries_by_repository = AsyncMock(return_value=0)
            mock_index_repo.upsert_index_job = AsyncMock()
            mock_index_repo.bulk_upsert_entries = capture_upsert
            MockIndexRepo.return_value = mock_index_repo

            from backend.app.symbol_index.services.index_service import SymbolIndexService

            service = SymbolIndexService(session=session)
            stats = await service.index_repository(REPO_ID)

        route_entries = [e for e in captured_entries if e.get("symbol_type") == "route"]
        assert len(route_entries) >= 1, "Expected at least one route symbol from FastAPI fixture"

    @pytest.mark.asyncio
    async def test_failed_file_does_not_abort_others(self) -> None:
        """A nonexistent file should be counted as failed, not abort indexing."""
        session = AsyncMock()

        bad_file = _make_mock_file(
            file_id=uuid.uuid4(),
            relative_path="nonexistent.py",
            absolute_path="/nonexistent/path/file.py",
        )
        good_fixture = FIXTURE_DIR / "sample_python.py"
        if not good_fixture.exists():
            pytest.skip("Python fixture file not found")

        good_file = _make_mock_file(
            file_id=uuid.uuid4(),
            relative_path="sample_python.py",
            absolute_path=str(good_fixture),
        )

        with (
            patch(
                "backend.app.symbol_index.services.index_service.RepositoryRepository"
            ) as MockRepoRepo,
            patch(
                "backend.app.symbol_index.services.index_service.FileRepository"
            ) as MockFileRepo,
            patch(
                "backend.app.symbol_index.services.index_service.SymbolRepository"
            ) as MockSymRepo,
            patch(
                "backend.app.symbol_index.services.index_service.SymbolIndexRepository"
            ) as MockIndexRepo,
        ):
            mock_repo_repo = AsyncMock()
            mock_repo_repo.get_by_id.return_value = _make_mock_repository()
            MockRepoRepo.return_value = mock_repo_repo

            mock_file_repo = AsyncMock()
            mock_file_repo.get_by_repository_id.return_value = [bad_file, good_file]
            MockFileRepo.return_value = mock_file_repo

            MockSymRepo.return_value = AsyncMock()

            mock_index_repo = AsyncMock()
            mock_index_repo.delete_entries_by_repository = AsyncMock(return_value=0)
            mock_index_repo.upsert_index_job = AsyncMock()
            mock_index_repo.bulk_upsert_entries = AsyncMock(return_value=5)
            MockIndexRepo.return_value = mock_index_repo

            from backend.app.symbol_index.services.index_service import SymbolIndexService

            service = SymbolIndexService(session=session)
            stats = await service.index_repository(REPO_ID)

        # Good file indexed, bad file skipped (not counted as indexed either)
        assert stats.total_files == 2
        # Good file should have been indexed
        assert stats.indexed_files >= 1
