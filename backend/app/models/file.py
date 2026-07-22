"""File ORM model for the Repository Scanner module.

Represents a single file discovered during a repository scan.
Each record stores filesystem metadata, language detection results,
SHA-256 hash, and scan lifecycle status.

This model intentionally stores *only metadata* — no source code content.
AST parsing is handled by a separate downstream module.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import AuditMixin, Base


class FileStatus(str, enum.Enum):
    """Lifecycle states for an individual file within a scan.

    Transitions::

        PENDING → SCANNED
                ↘ FAILED
                ↘ IGNORED
    """

    PENDING = "PENDING"
    SCANNED = "SCANNED"
    FAILED = "FAILED"
    IGNORED = "IGNORED"


class ProgrammingLanguage(str, enum.Enum):
    """Detected programming languages supported by the scanner.

    The ``UNKNOWN`` variant is used when the file extension does not
    match any entry in the language detection table.
    """

    PYTHON = "Python"
    JAVA = "Java"
    JAVASCRIPT = "JavaScript"
    TYPESCRIPT = "TypeScript"
    GO = "Go"
    C = "C"
    CPP = "C++"
    RUST = "Rust"
    KOTLIN = "Kotlin"
    SWIFT = "Swift"
    PHP = "PHP"
    RUBY = "Ruby"
    MARKDOWN = "Markdown"
    JSON = "JSON"
    YAML = "YAML"
    DOCKERFILE = "Dockerfile"
    TERRAFORM = "Terraform"
    SHELL = "Shell"
    HTML = "HTML"
    CSS = "CSS"
    SQL = "SQL"
    UNKNOWN = "Unknown"


class RepositoryFile(Base, AuditMixin):
    """SQLAlchemy ORM model for files discovered during a repository scan.

    Inherits ``id`` (UUID PK), ``created_at``, and ``updated_at``
    from :class:`~backend.app.db.base.AuditMixin`.

    Attributes:
        repository_id: FK to the owning repository.
        relative_path: Path relative to the repository root (e.g. ``src/api.py``).
        absolute_path: Fully-qualified filesystem path used during scanning.
        file_name: Base name of the file (e.g. ``api.py``).
        extension: File extension without leading dot (e.g. ``py``).
                   Empty string when there is no extension.
        language: Detected programming language.
        mime_type: MIME type as a string (e.g. ``text/x-python``).
        size_bytes: File size in bytes.
        sha256: SHA-256 hex digest of the file contents.
        is_binary: ``True`` when the file is detected as binary.
        is_hidden: ``True`` when the file or any parent directory starts with ``"."``.
        last_modified: Filesystem last-modification timestamp (UTC).
        scan_status: Current scan lifecycle status.
    """

    __tablename__ = "repository_files"

    # ── Foreign key ───────────────────────────────────────────────────────────
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK to the parent repository",
    )

    # ── Path fields ───────────────────────────────────────────────────────────
    relative_path: Mapped[str] = mapped_column(
        String(4096),
        nullable=False,
        comment="Path relative to repository root (POSIX separators)",
    )
    absolute_path: Mapped[str] = mapped_column(
        String(4096),
        nullable=False,
        comment="Absolute filesystem path to the file",
    )
    file_name: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        index=True,
        comment="Base name of the file including extension",
    )
    extension: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        server_default="",
        index=True,
        comment="File extension without leading dot; empty when absent",
    )

    # ── Language / type detection ─────────────────────────────────────────────
    language: Mapped[ProgrammingLanguage] = mapped_column(
        Enum(ProgrammingLanguage, name="programming_language", create_type=True),
        nullable=False,
        default=ProgrammingLanguage.UNKNOWN,
        index=True,
        comment="Detected programming language",
    )
    mime_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="application/octet-stream",
        server_default="application/octet-stream",
        comment="MIME type string",
    )

    # ── File attributes ───────────────────────────────────────────────────────
    size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
        comment="File size in bytes",
    )
    sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="SHA-256 hex digest of file contents; NULL for binary/ignored files",
    )
    is_binary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True when the file is detected as binary",
    )
    is_hidden: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True when the file or a parent directory name begins with a dot",
    )
    last_modified: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Filesystem last-modification timestamp (UTC)",
    )

    # ── Scan lifecycle ────────────────────────────────────────────────────────
    scan_status: Mapped[FileStatus] = mapped_column(
        Enum(FileStatus, name="file_status", create_type=True),
        nullable=False,
        default=FileStatus.PENDING,
        server_default=FileStatus.PENDING.value,
        index=True,
        comment="Scan lifecycle status of this file",
    )

    # ── ORM relationship (back-reference only; avoids circular import) ────────
    # Intentionally not declared here to keep the model self-contained.
    # Use explicit joins when querying across tables.

    # ── Table-level indexes ───────────────────────────────────────────────────
    __table_args__ = (
        Index(
            "ix_repository_files_repo_rel_path",
            "repository_id",
            "relative_path",
            unique=True,
        ),
        Index(
            "ix_repository_files_repo_language",
            "repository_id",
            "language",
        ),
        Index(
            "ix_repository_files_sha256",
            "sha256",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<RepositoryFile id={self.id} "
            f"relative_path={self.relative_path!r} "
            f"language={self.language.value} "
            f"status={self.scan_status.value}>"
        )
