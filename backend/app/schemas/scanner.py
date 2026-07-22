"""Pydantic schemas for the Repository Scanner module.

Defines response models for scan initiation, individual file metadata,
directory tree nodes, and the full repository manifest.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.app.models.file import FileStatus, ProgrammingLanguage


# ── File metadata ──────────────────────────────────────────────────────────────


class FileMetadataResponse(BaseModel):
    """Full metadata for a single scanned file.

    Attributes mirror the :class:`~backend.app.models.file.RepositoryFile` ORM model.
    """

    id: uuid.UUID = Field(description="File record primary key (UUID)")
    repository_id: uuid.UUID = Field(description="Owning repository UUID")
    relative_path: str = Field(description="Path relative to repository root (POSIX separators)")
    absolute_path: str = Field(description="Absolute filesystem path")
    file_name: str = Field(description="Base name of the file including extension")
    extension: str = Field(description="File extension without leading dot; empty when absent")
    language: ProgrammingLanguage = Field(description="Detected programming language")
    mime_type: str = Field(description="MIME type string")
    size_bytes: int = Field(description="File size in bytes")
    sha256: str | None = Field(default=None, description="SHA-256 hex digest; None for binary files")
    is_binary: bool = Field(description="True when the file is detected as binary")
    is_hidden: bool = Field(
        description="True when the file or a parent directory name begins with a dot"
    )
    last_modified: datetime | None = Field(
        default=None, description="Filesystem last-modification timestamp (UTC)"
    )
    scan_status: FileStatus = Field(description="Scan lifecycle status")
    created_at: datetime = Field(description="Record creation timestamp")
    updated_at: datetime = Field(description="Record last-update timestamp")

    model_config = {"from_attributes": True}


# ── Scan lifecycle ─────────────────────────────────────────────────────────────


class ScanStatus(str):
    """String literals for scan lifecycle states (not an enum to avoid DB coupling)."""

    PENDING = "PENDING"
    SCANNING = "SCANNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ScanInitiatedResponse(BaseModel):
    """Returned immediately when a scan is enqueued.

    Attributes:
        repository_id: The repository being scanned.
        status: Always ``"SCANNING"`` when the task is successfully enqueued.
        message: Human-readable confirmation message.
    """

    repository_id: uuid.UUID = Field(description="Repository being scanned")
    status: str = Field(description="Scan lifecycle status")
    message: str = Field(description="Human-readable confirmation")


# ── Language statistics ────────────────────────────────────────────────────────


class LanguageStats(BaseModel):
    """Per-language file count and byte total within a repository.

    Attributes:
        language: The programming language name.
        file_count: Number of files detected as this language.
        total_bytes: Sum of size_bytes across all files of this language.
        percentage: Percentage of total source files (0.0–100.0).
    """

    language: str = Field(description="Programming language name")
    file_count: int = Field(description="Number of files of this language")
    total_bytes: int = Field(description="Total bytes across all files of this language")
    percentage: float = Field(description="Percentage of total scanned files (0.0–100.0)")


# ── Directory tree ─────────────────────────────────────────────────────────────


class DirectoryNode(BaseModel):
    """A node in the repository directory tree.

    Attributes:
        name: Directory or file name.
        path: Path relative to repository root.
        is_file: ``True`` for leaf nodes (files); ``False`` for directory nodes.
        language: Language if ``is_file`` is ``True``, otherwise ``None``.
        size_bytes: File size if ``is_file`` is ``True``, otherwise ``None``.
        children: Nested directory nodes (empty list for file nodes).
    """

    name: str = Field(description="Entry name (directory or file)")
    path: str = Field(description="Path relative to repository root")
    is_file: bool = Field(description="True for file leaves; False for directory nodes")
    language: str | None = Field(
        default=None, description="Detected language (file nodes only)"
    )
    size_bytes: int | None = Field(
        default=None, description="File size in bytes (file nodes only)"
    )
    children: list["DirectoryNode"] = Field(
        default_factory=list,
        description="Child nodes (directory nodes only)",
    )


# Allow forward reference resolution
DirectoryNode.model_rebuild()


# ── Scan statistics ────────────────────────────────────────────────────────────


class ScanStatistics(BaseModel):
    """Aggregate statistics collected during a repository scan.

    Attributes:
        total_files: Total number of file entries encountered (including ignored).
        scanned_files: Files successfully scanned and stored (status=SCANNED).
        ignored_files: Files explicitly skipped (ignored dir/extension/size).
        failed_files: Files that raised an error during processing.
        binary_files: Files detected as binary.
        hidden_files: Files or paths where ``is_hidden=True``.
        total_bytes: Sum of size_bytes across all scanned files.
        source_files: Files with a known non-Unknown programming language.
        documentation_files: Files detected as Markdown.
        languages_found: Distinct languages detected (excluding Unknown).
        scan_duration_seconds: Wall-clock time for the full scan (seconds).
    """

    total_files: int = Field(default=0, description="Total file entries encountered")
    scanned_files: int = Field(default=0, description="Files successfully scanned")
    ignored_files: int = Field(default=0, description="Files intentionally skipped")
    failed_files: int = Field(default=0, description="Files that caused scan errors")
    binary_files: int = Field(default=0, description="Files detected as binary")
    hidden_files: int = Field(default=0, description="Files with is_hidden=True")
    total_bytes: int = Field(default=0, description="Sum of size_bytes across scanned files")
    source_files: int = Field(
        default=0, description="Files with a known (non-Unknown) programming language"
    )
    documentation_files: int = Field(
        default=0, description="Markdown documentation files"
    )
    languages_found: list[str] = Field(
        default_factory=list,
        description="Distinct language names detected (excluding Unknown)",
    )
    scan_duration_seconds: float = Field(
        default=0.0, description="Wall-clock time for the full scan (seconds)"
    )


# ── Repository manifest ────────────────────────────────────────────────────────


class RepositoryManifest(BaseModel):
    """Complete manifest of a scanned repository.

    This is the primary output of the scanner module and the input
    consumed by the AST Parser module.

    Attributes:
        repository_id: Repository UUID.
        scan_status: Final scan status (``COMPLETED`` or ``FAILED``).
        statistics: Aggregate statistics for the scan.
        languages: Per-language breakdown with file counts and byte totals.
        directory_tree: Hierarchical tree representation of the repository.
        scanned_at: Timestamp when the manifest was generated.
    """

    repository_id: uuid.UUID = Field(description="Repository UUID")
    scan_status: str = Field(description="Final scan status")
    statistics: ScanStatistics = Field(description="Aggregate scan statistics")
    languages: list[LanguageStats] = Field(
        default_factory=list,
        description="Per-language breakdown sorted by file_count descending",
    )
    directory_tree: list[DirectoryNode] = Field(
        default_factory=list,
        description="Root-level directory tree nodes",
    )
    scanned_at: datetime = Field(description="Manifest generation timestamp (UTC)")
