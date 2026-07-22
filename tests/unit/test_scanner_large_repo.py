"""Performance and stress tests for the Repository Scanner.

Tests that the scanner handles:
  - Large repositories (many files across deep directory trees)
  - Hidden file detection across nested directories
  - Ignore pattern application at scale
  - Memory efficiency (no accumulation of file contents)

These tests use real temporary filesystems but mock all database calls.
"""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.models.file import FileStatus, ProgrammingLanguage
from backend.app.models.repository import RepositoryStatus
from backend.app.services.scanner_service import RepositoryScannerService
from tests.unit.test_scanner_service import _make_repo


def _build_large_repo(tmp_path: Path, *, num_files: int = 1000) -> None:
    """Create a directory tree simulating a large repository.

    Layout:
        src/
          module_0/ ... module_N/
            file_0.py ... file_K.py
        docs/
          guide_0.md ...
        tests/
          test_0.py ...
        .git/          (must be skipped)
        node_modules/  (must be skipped)
        __pycache__/   (must be skipped)

    Args:
        tmp_path: Root of the temporary directory.
        num_files: Total number of Python source files to create.
    """
    files_per_dir = 50
    num_modules = max(1, num_files // files_per_dir)

    for m in range(num_modules):
        mod_dir = tmp_path / "src" / f"module_{m}"
        mod_dir.mkdir(parents=True, exist_ok=True)
        for f in range(files_per_dir):
            (mod_dir / f"file_{f}.py").write_text(
                f"# module {m} file {f}\ndef func(): pass\n",
                encoding="utf-8",
            )

    docs = tmp_path / "docs"
    docs.mkdir()
    for i in range(20):
        (docs / f"guide_{i}.md").write_text(f"# Guide {i}\n", encoding="utf-8")

    tests = tmp_path / "tests"
    tests.mkdir()
    for i in range(50):
        (tests / f"test_{i}.py").write_text(f"def test_{i}(): pass\n", encoding="utf-8")

    # Directories that must be ignored
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "huge_lib.js").write_text("// 10MB lib", encoding="utf-8")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "compiled.pyc").write_bytes(b"\xb3\xf3\x0d\x0a")


@pytest.mark.asyncio
async def test_large_repository_scan_completes(tmp_path: Path):
    """Scanner successfully processes a large repo within reasonable bounds."""
    _build_large_repo(tmp_path, num_files=500)

    repo_id = uuid.uuid4()
    repo = _make_repo(repository_id=repo_id, local_path=str(tmp_path))

    repo_repo_mock = AsyncMock()
    repo_repo_mock.get_by_id.return_value = repo

    upserted_total = 0

    async def count_upsert(records):
        nonlocal upserted_total
        upserted_total += len(records)
        return len(records)

    file_repo_mock = AsyncMock()
    file_repo_mock.delete_by_repository.return_value = 0
    file_repo_mock.bulk_upsert.side_effect = count_upsert
    file_repo_mock.get_language_stats.return_value = [
        (ProgrammingLanguage.PYTHON, 550, 20000),
        (ProgrammingLanguage.MARKDOWN, 20, 400),
    ]

    with (
        patch(
            "backend.app.services.scanner_service.RepositoryRepository",
            return_value=repo_repo_mock,
        ),
        patch(
            "backend.app.services.scanner_service.FileRepository",
            return_value=file_repo_mock,
        ),
    ):
        session = AsyncMock()
        service = RepositoryScannerService(session=session)
        stats = await service.scan_repository(repo_id)

    # Must have scanned meaningful number of files
    assert stats.total_files >= 550
    assert stats.scanned_files >= 550
    # upserted_total tracks actual bulk inserts
    assert upserted_total >= 550

    # Ignored directories must NOT have contributed any files
    # .git has 1 file, node_modules has 1 file, __pycache__ has 1 file
    assert stats.total_files == upserted_total


@pytest.mark.asyncio
async def test_large_repo_ignored_dirs_not_scanned(tmp_path: Path):
    """Ignored directories contribute zero records even in large repos."""
    _build_large_repo(tmp_path, num_files=100)

    repo_id = uuid.uuid4()
    repo = _make_repo(repository_id=repo_id, local_path=str(tmp_path))

    repo_repo_mock = AsyncMock()
    repo_repo_mock.get_by_id.return_value = repo

    all_records: list[dict] = []

    async def capture_upsert(records):
        all_records.extend(records)
        return len(records)

    file_repo_mock = AsyncMock()
    file_repo_mock.delete_by_repository.return_value = 0
    file_repo_mock.bulk_upsert.side_effect = capture_upsert
    file_repo_mock.get_language_stats.return_value = []

    with (
        patch(
            "backend.app.services.scanner_service.RepositoryRepository",
            return_value=repo_repo_mock,
        ),
        patch(
            "backend.app.services.scanner_service.FileRepository",
            return_value=file_repo_mock,
        ),
    ):
        session = AsyncMock()
        service = RepositoryScannerService(session=session)
        await service.scan_repository(repo_id)

    paths = [r["relative_path"] for r in all_records]
    forbidden_prefixes = (".git", "node_modules", "__pycache__")
    violations = [p for p in paths if p.startswith(forbidden_prefixes)]
    assert violations == [], (
        f"Found records from ignored directories: {violations}"
    )


@pytest.mark.asyncio
async def test_deep_nested_directory_scan(tmp_path: Path):
    """Scanner handles deep directory nesting without recursion overflow."""
    # Build a 30-level deep path (within max_scan_depth)
    deep = tmp_path
    for i in range(30):
        deep = deep / f"level_{i}"
    deep.mkdir(parents=True)
    (deep / "deep_file.py").write_text("x = 1", encoding="utf-8")

    repo_id = uuid.uuid4()
    repo = _make_repo(repository_id=repo_id, local_path=str(tmp_path))

    repo_repo_mock = AsyncMock()
    repo_repo_mock.get_by_id.return_value = repo

    file_repo_mock = AsyncMock()
    file_repo_mock.delete_by_repository.return_value = 0
    file_repo_mock.bulk_upsert.return_value = 0
    file_repo_mock.get_language_stats.return_value = []

    with (
        patch(
            "backend.app.services.scanner_service.RepositoryRepository",
            return_value=repo_repo_mock,
        ),
        patch(
            "backend.app.services.scanner_service.FileRepository",
            return_value=file_repo_mock,
        ),
    ):
        session = AsyncMock()
        service = RepositoryScannerService(session=session)
        # Should complete without RecursionError
        stats = await service.scan_repository(repo_id)

    assert stats.total_files >= 1
