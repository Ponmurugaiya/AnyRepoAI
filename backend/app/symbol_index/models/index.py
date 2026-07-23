"""SQLAlchemy ORM model for the canonical Symbol Index.

The ``symbol_index`` table is the single source of truth for all code
entities extracted from repository source files. Every meaningful code
symbol — regardless of the language that produced it — is normalised into
a :class:`SymbolIndexEntry` with a globally unique identity.

Future modules (Dependency Graph, Embedding Pipeline, AI Chat) consume
this table directly instead of reparsing source files.

Design decisions:
    - ``qualified_name`` is unique per repository. When two symbols share the
      same qualified name (e.g. method overloads), the last indexed one wins
      via an ``ON CONFLICT DO UPDATE`` upsert.
    - ``module_name`` and ``namespace`` store the structural context so callers
      can reconstruct the fully-qualified path without re-scanning files.
    - Boolean flags are denormalised onto the entry for query performance.
    - ``parent_symbol_id`` is a self-referential UUID that enables the
      parent-child tree traversal without a recursive CTE on ``qualified_name``.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import (
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import AuditMixin, Base


class IndexStatus(str, enum.Enum):
    """Lifecycle state of a repository symbol-index run.

    Transitions::

        QUEUED → INDEXING → COMPLETED
                          ↘ FAILED
    """

    QUEUED = "QUEUED"
    INDEXING = "INDEXING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SymbolIndex(Base, AuditMixin):
    """Tracks the symbol-indexing lifecycle for one repository.

    One record is created when a new indexing job is enqueued and updated
    as the job progresses. Re-indexing upserts this record so only one job
    record exists per repository at any time.

    Attributes:
        repository_id: FK to ``repositories.id``.
        status: Current lifecycle stage.
        total_files: Total files eligible for indexing.
        indexed_files: Files that have been fully indexed.
        failed_files: Files that failed during indexing.
        total_symbols: Total symbols written to the index.
        duplicate_symbols: Symbols skipped due to qualified-name collision.
        error_message: Last error detail when status=FAILED.
        index_duration_seconds: Wall-clock time for the last completed run.
    """

    __tablename__ = "symbol_index_jobs"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="FK to repositories.id (1:1 per repository)",
    )
    status: Mapped[IndexStatus] = mapped_column(
        Enum(IndexStatus, name="index_status", create_type=True),
        nullable=False,
        default=IndexStatus.QUEUED,
        server_default=IndexStatus.QUEUED.value,
        index=True,
        comment="Current indexing lifecycle status",
    )
    total_files: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Total files eligible for indexing",
    )
    indexed_files: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Files successfully indexed",
    )
    failed_files: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Files that failed to index",
    )
    total_symbols: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Total entries written to symbol_index_entries",
    )
    duplicate_symbols: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Symbols skipped due to qualified_name collision",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Last failure reason (when status=FAILED)",
    )
    index_duration_seconds: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0",
        comment="Wall-clock duration of the last completed run (seconds)",
    )

    __table_args__ = (
        Index("ix_symbol_index_jobs_repo_status", "repository_id", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SymbolIndex repository_id={self.repository_id} "
            f"status={self.status.value}>"
        )


class SymbolIndexEntry(Base, AuditMixin):
    """A single canonical code symbol in the Symbol Index.

    Every meaningful symbol extracted from any supported language is
    normalised into this table. The combination of ``repository_id`` and
    ``qualified_name`` is globally unique within the index.

    Attributes:
        repository_id: Owning repository UUID.
        file_id: Source file UUID (FK to ``repository_files.id``).
        language: Source language (e.g. ``"Python"``, ``"TypeScript"``).
        symbol_type: Classification of the symbol.
        name: Short unqualified name (e.g. ``"login"``).
        qualified_name: Fully-qualified name (e.g. ``"app.auth.AuthService.login"``).
        display_name: Human-readable label (e.g. ``"AuthService.login"``).
        parent_symbol_id: UUID of the enclosing symbol record, or ``None``
            for top-level symbols.
        module_name: Dot-separated module path (e.g. ``"app.auth"``).
        namespace: Language-specific namespace or package (e.g. ``"com.example"``).
        signature: Normalised signature (e.g. ``"login(username: str, password: str) -> Token"``).
        return_type: Return type annotation string.
        visibility: Access modifier (public/private/protected/internal/unknown).
        is_static: True for static methods/fields.
        is_async: True for coroutines and async functions.
        is_exported: True when the symbol is exported (ES6, TypeScript).
        is_deprecated: True when the symbol carries a deprecation annotation.
        documentation: Extracted docstring / JavaDoc / JSDoc text.
        start_line: 1-indexed start line in the source file.
        end_line: 1-indexed end line in the source file.
        start_column: 0-indexed start column.
        end_column: 0-indexed end column.
    """

    __tablename__ = "symbol_index_entries"

    # ── Identity ──────────────────────────────────────────────────────────────
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Owning repository UUID",
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Source file UUID",
    )

    # ── Classification ────────────────────────────────────────────────────────
    language: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="Source programming language",
    )
    symbol_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="Symbol classification (class, function, method, …)",
    )

    # ── Naming ────────────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        index=True,
        comment="Short unqualified symbol name",
    )
    qualified_name: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        index=True,
        comment="Fully-qualified symbol name (unique per repository)",
    )
    display_name: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="Human-readable label for UI display",
    )

    # ── Hierarchy ─────────────────────────────────────────────────────────────
    parent_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        # Self-referential FK — intentionally no ON DELETE CASCADE so that
        # deleting a parent does not cascade-delete children in one shot;
        # service code explicitly clears children first.
        ForeignKey("symbol_index_entries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="UUID of the enclosing symbol (NULL for top-level)",
    )

    # ── Structural context ────────────────────────────────────────────────────
    module_name: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="Module or package path (e.g. app.auth)",
    )
    namespace: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="Language-specific namespace or package declaration",
    )

    # ── Signature ─────────────────────────────────────────────────────────────
    signature: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Normalised human-readable signature",
    )
    return_type: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="Return type annotation string",
    )

    # ── Access modifiers ──────────────────────────────────────────────────────
    visibility: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="unknown",
        server_default="unknown",
        comment="Access modifier: public/private/protected/internal/unknown",
    )
    is_static: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True for static methods / class-level members",
    )
    is_async: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True for async/coroutine functions",
    )
    is_exported: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True when symbol is exported (ES6/TypeScript export)",
    )
    is_deprecated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True when symbol carries a deprecation marker",
    )

    # ── Documentation ─────────────────────────────────────────────────────────
    documentation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Extracted docstring / JavaDoc / JSDoc text",
    )

    # ── Source location ───────────────────────────────────────────────────────
    start_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="1-indexed start line",
    )
    end_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="1-indexed end line",
    )
    start_column: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="0-indexed start column",
    )
    end_column: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="0-indexed end column",
    )

    # ── Table constraints and indexes ─────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint(
            "repository_id",
            "qualified_name",
            name="uq_symbol_index_repo_qualified_name",
        ),
        Index("ix_sie_repo_id", "repository_id"),
        Index("ix_sie_file_id", "file_id"),
        Index("ix_sie_language", "language"),
        Index("ix_sie_symbol_type", "symbol_type"),
        Index("ix_sie_name", "name"),
        Index("ix_sie_qualified_name", "qualified_name"),
        Index("ix_sie_parent_symbol_id", "parent_symbol_id"),
        Index("ix_sie_repo_language", "repository_id", "language"),
        Index("ix_sie_repo_type", "repository_id", "symbol_type"),
        Index("ix_sie_repo_file", "repository_id", "file_id"),
        Index("ix_sie_repo_name", "repository_id", "name"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SymbolIndexEntry {self.symbol_type} "
            f"qualified_name={self.qualified_name!r}>"
        )
