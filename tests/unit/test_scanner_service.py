"""Unit tests for RepositoryScannerService.

All file I/O and database interactions are mocked so these tests run
without external dependencies.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.core.exceptions import RepositoryNotFoundError, RepositoryNotReadyError
from backend.app.models.file import FileStatus, ProgrammingLanguage
from backend.app.models.repository import Repository, RepositoryStatus
from backend.app.services.scanner_service import RepositoryScannerService


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_repo(
    *,
    repository_id: uuid.UUID | None = None,
    local_path: str = "/storage/repos/test-id",
    status: RepositoryStatus = RepositoryStatus.READY,
) -> Repository:
    """Build a mock Repository ORM instance."""
    repo = MagicMock(spec=Repository)
    repo.id = repository_id or uuid.uuid4()
    repo.owner = "octocat"
    repo.name = "test-repo"
    repo.full_name = "octocat/test-repo"
    repo.github_url = "https://github.com/octocat/test-repo"
    repo.clone_status = status
    repo.local_path = local_path
    return repo


# ── detect_language ────────────────────────────────────────────────────────────


def test_detect_language_python():
    """A .py extension maps to Python."""
    lang = RepositoryScannerService.detect_language("api.py", "py")
    assert lang == ProgrammingLanguage.PYTHON


def test_detect_language_typescript():
    """A .ts extension maps to TypeScript."""
    lang = RepositoryScannerService.detect_language("index.ts", "ts")
    assert lang == ProgrammingLanguage.TYPESCRIPT


def test_detect_language_dockerfile():
    """A file named 'Dockerfile' maps to Dockerfile language."""
    lang = RepositoryScannerService.detect_language("Dockerfile", "")
    assert lang == ProgrammingLanguage.DOCKERFILE


def test_detect_language_dockerfile_variant():
    """A file named 'Dockerfile.dev' also maps to Dockerfile."""
    lang = RepositoryScannerService.detect_language("Dockerfile.dev", "dev")
    assert lang == ProgrammingLanguage.DOCKERFILE


def test_detect_language_unknown():
    """A file with an unmapped extension returns UNKNOWN."""
    lang = RepositoryScannerService.detect_language("readme.xyz", "xyz")
    assert lang == ProgrammingLanguage.UNKNOWN


def test_detect_language_no_extension():
    """A file with no extension returns UNKNOWN."""
    lang = RepositoryScannerService.detect_language("LICENSE", "")
    assert lang == ProgrammingLanguage.UNKNOWN


# ── detect_binary ──────────────────────────────────────────────────────────────


def test_detect_binary_by_extension(tmp_path: Path):
    """A file with a known binary extension is detected as binary."""
    test_file = tmp_path / "test.exe"
    test_file.write_bytes(b"fake executable")

    is_binary = RepositoryScannerService.detect_binary("test.exe", "exe", str(test_file))
    assert is_binary is True


def test_detect_binary_by_sniff(tmp_path: Path):
    """A file with a null byte is detected as binary via byte-sniff."""
    test_file = tmp_path / "test.dat"
    test_file.write_bytes(b"some text\x00binary data")

    is_binary = RepositoryScannerService.detect_binary("test.dat", "dat", str(test_file))
    assert is_binary is True


def test_detect_binary_text_file(tmp_path: Path):
    """A plain text file without null bytes is not binary."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello world", encoding="utf-8")

    is_binary = RepositoryScannerService.detect_binary("test.txt", "txt", str(test_file))
    assert is_binary is False


# ── compute_hash ───────────────────────────────────────────────────────────────


def test_compute_hash_matches_known_value(tmp_path: Path):
    """SHA-256 hash of a known string matches the expected digest."""
    test_file = tmp_path / "test.txt"
    content = b"hello world\n"
    test_file.write_bytes(content)

    import hashlib

    expected = hashlib.sha256(content).hexdigest()
    result = RepositoryScannerService.compute_hash(str(test_file))

    assert result == expected


def test_compute_hash_different_files_differ(tmp_path: Path):
    """Two files with different contents produce different hashes."""
    file1 = tmp_path / "file1.txt"
    file2 = tmp_path / "file2.txt"
    file1.write_text("content A", encoding="utf-8")
    file2.write_text("content B", encoding="utf-8")

    hash1 = RepositoryScannerService.compute_hash(str(file1))
    hash2 = RepositoryScannerService.compute_hash(str(file2))

    assert hash1 != hash2


# ── scan_repository (high-level) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_repository_not_found():
    """scan_repository with unknown UUID must raise RepositoryNotFoundError."""
    session = AsyncMock()
    repo_repo = AsyncMock()
    repo_repo.get_by_id.return_value = None

    with patch(
        "backend.app.services.scanner_service.RepositoryRepository",
        return_value=repo_repo,
    ):
        service = RepositoryScannerService(session=session)
        with pytest.raises(RepositoryNotFoundError):
            await service.scan_repository(uuid.uuid4())


@pytest.mark.asyncio
async def test_scan_repository_not_ready():
    """scan_repository with status != READY must raise RepositoryNotReadyError."""
    session = AsyncMock()
    repo = _make_repo(status=RepositoryStatus.CLONING)
    repo_repo = AsyncMock()
    repo_repo.get_by_id.return_value = repo

    with patch(
        "backend.app.services.scanner_service.RepositoryRepository",
        return_value=repo_repo,
    ):
        service = RepositoryScannerService(session=session)
        with pytest.raises(RepositoryNotReadyError):
            await service.scan_repository(repo.id)


@pytest.mark.asyncio
async def test_scan_repository_runs_full_pipeline(tmp_path: Path):
    """scan_repository walks a real directory tree and returns statistics."""
    # Build a small but realistic repo layout
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".git").mkdir()  # must be ignored
    (tmp_path / "node_modules").mkdir()  # must be ignored

    (tmp_path / "src" / "api.py").write_text("# python api", encoding="utf-8")
    (tmp_path / "src" / "utils.ts").write_text("export {}", encoding="utf-8")
    (tmp_path / "tests" / "test_api.py").write_text("# tests", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Readme", encoding="utf-8")
    (tmp_path / ".git" / "config").write_text("[core]", encoding="utf-8")
    (tmp_path / "node_modules" / "lodash.js").write_text("// lodash", encoding="utf-8")

    repo_id = uuid.uuid4()
    repo = _make_repo(repository_id=repo_id, local_path=str(tmp_path))

    repo_repo_mock = AsyncMock()
    repo_repo_mock.get_by_id.return_value = repo

    file_repo_mock = AsyncMock()
    file_repo_mock.delete_by_repository.return_value = 0
    file_repo_mock.bulk_upsert.return_value = 0
    file_repo_mock.get_language_stats.return_value = [
        (ProgrammingLanguage.PYTHON, 2, 24),
        (ProgrammingLanguage.TYPESCRIPT, 1, 14),
        (ProgrammingLanguage.MARKDOWN, 1, 10),
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

    # .git and node_modules are ignored directories — their files must not appear
    assert stats.total_files >= 4  # src/api.py, src/utils.ts, tests/test_api.py, README.md
    assert stats.scanned_files >= 4
    # Verify bulk_upsert was called
    assert file_repo_mock.bulk_upsert.called


# ── Ignore directory filter ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_ignores_git_directory(tmp_path: Path):
    """The .git directory is never descended into."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")

    repo_id = uuid.uuid4()
    repo = _make_repo(repository_id=repo_id, local_path=str(tmp_path))

    repo_repo_mock = AsyncMock()
    repo_repo_mock.get_by_id.return_value = repo

    file_repo_mock = AsyncMock()
    file_repo_mock.delete_by_repository.return_value = 0
    file_repo_mock.bulk_upsert.return_value = 0
    file_repo_mock.get_language_stats.return_value = []

    captured_records: list[list[dict]] = []

    async def capture_upsert(records):
        captured_records.append(list(records))
        return len(records)

    file_repo_mock.bulk_upsert.side_effect = capture_upsert

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

    all_paths = [
        record["relative_path"]
        for batch in captured_records
        for record in batch
    ]
    # No record should start with .git/
    assert not any(p.startswith(".git") for p in all_paths), (
        f"Found .git paths in scanned records: {all_paths}"
    )


# ── Hidden file detection ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_marks_hidden_files(tmp_path: Path):
    """Files whose name starts with '.' are marked is_hidden=True."""
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")

    repo_id = uuid.uuid4()
    repo = _make_repo(repository_id=repo_id, local_path=str(tmp_path))

    repo_repo_mock = AsyncMock()
    repo_repo_mock.get_by_id.return_value = repo

    file_repo_mock = AsyncMock()
    file_repo_mock.delete_by_repository.return_value = 0
    file_repo_mock.bulk_upsert.return_value = 0
    file_repo_mock.get_language_stats.return_value = []

    captured_records: list[dict] = []

    async def capture_upsert(records):
        captured_records.extend(records)
        return len(records)

    file_repo_mock.bulk_upsert.side_effect = capture_upsert

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

    hidden = [r for r in captured_records if r["relative_path"] == ".env"]
    visible = [r for r in captured_records if r["relative_path"] == "main.py"]

    assert len(hidden) == 1, "Expected .env to be recorded"
    assert hidden[0]["is_hidden"] is True
    assert len(visible) == 1, "Expected main.py to be recorded"
    assert visible[0]["is_hidden"] is False


# ── Binary file detection ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_binary_files_have_no_hash(tmp_path: Path):
    """Binary files are recorded with is_binary=True and sha256=None."""
    binary_file = tmp_path / "image.png"
    binary_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    repo_id = uuid.uuid4()
    repo = _make_repo(repository_id=repo_id, local_path=str(tmp_path))

    repo_repo_mock = AsyncMock()
    repo_repo_mock.get_by_id.return_value = repo

    file_repo_mock = AsyncMock()
    file_repo_mock.delete_by_repository.return_value = 0
    file_repo_mock.bulk_upsert.return_value = 0
    file_repo_mock.get_language_stats.return_value = []

    captured_records: list[dict] = []

    async def capture_upsert(records):
        captured_records.extend(records)
        return len(records)

    file_repo_mock.bulk_upsert.side_effect = capture_upsert

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

    png_records = [r for r in captured_records if r["file_name"] == "image.png"]
    assert len(png_records) == 1
    assert png_records[0]["scan_status"] == FileStatus.IGNORED


# ── Hash verification ──────────────────────────────────────────────────────────


def test_hash_is_deterministic(tmp_path: Path):
    """Computing the hash twice on the same file yields the same result."""
    test_file = tmp_path / "stable.py"
    test_file.write_text("x = 42\n", encoding="utf-8")

    hash1 = RepositoryScannerService.compute_hash(str(test_file))
    hash2 = RepositoryScannerService.compute_hash(str(test_file))

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex digest is always 64 chars


def test_hash_changes_on_file_modification(tmp_path: Path):
    """Modifying a file changes its hash."""
    test_file = tmp_path / "changing.py"
    test_file.write_text("x = 1\n", encoding="utf-8")
    hash1 = RepositoryScannerService.compute_hash(str(test_file))

    test_file.write_text("x = 2\n", encoding="utf-8")
    hash2 = RepositoryScannerService.compute_hash(str(test_file))

    assert hash1 != hash2
