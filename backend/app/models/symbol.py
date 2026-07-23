"""SQLAlchemy ORM models for the Code Intelligence Engine.

Defines the persistent schema for symbols, imports, calls, routes, and
classes/functions extracted by the language parsers.

These models are intentionally decoupled from the parser domain models
(``app/parsers/models/symbols.py``) — the ORM layer owns persistence
concerns while the parser layer owns extraction logic.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import AuditMixin, Base


# ── Enums ──────────────────────────────────────────────────────────────────────

class ParseStatus(str, enum.Enum):
    """Lifecycle states for a file's parse job.

    Transitions::

        QUEUED → PARSING → COMPLETED
                         ↘ FAILED
    """

    QUEUED = "QUEUED"
    PARSING = "PARSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SymbolType(str, enum.Enum):
    """Classification of an extracted code symbol."""

    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    CONSTRUCTOR = "constructor"
    VARIABLE = "variable"
    CONSTANT = "constant"
    ENUM = "enum"
    INTERFACE = "interface"
    STRUCT = "struct"
    MODULE = "module"
    PACKAGE = "package"
    ROUTE = "route"
    DECORATOR = "decorator"
    ANNOTATION = "annotation"


class Visibility(str, enum.Enum):
    """Symbol access level / visibility."""

    PUBLIC = "public"
    PRIVATE = "private"
    PROTECTED = "protected"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


# ── Parse job tracking ─────────────────────────────────────────────────────────

class FileParseJob(Base, AuditMixin):
    """Tracks the parse status of an individual file.

    One record per ``repository_file`` entry. Re-parsing resets this record
    rather than creating duplicates.

    Attributes:
        file_id: FK to ``repository_files.id``.
        repository_id: FK to ``repositories.id`` (denormalized for fast queries).
        parse_status: Current lifecycle stage.
        language: Language used for parsing.
        error_message: Last failure reason, when status=FAILED.
        parse_duration_ms: Wall-clock time for the last successful parse.
        symbol_count: Total symbols extracted.
        import_count: Total imports extracted.
        call_count: Total calls extracted.
        function_count: Total functions extracted.
        class_count: Total classes extracted.
        route_count: Total routes detected.
    """

    __tablename__ = "file_parse_jobs"

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="FK to repository_files.id (1:1)",
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Denormalized FK to repositories.id for bulk queries",
    )
    parse_status: Mapped[ParseStatus] = mapped_column(
        Enum(ParseStatus, name="parse_status", create_type=True),
        nullable=False,
        default=ParseStatus.QUEUED,
        server_default=ParseStatus.QUEUED.value,
        index=True,
        comment="Current parse lifecycle status",
    )
    language: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Language used for parsing"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Last parse error message"
    )
    parse_duration_ms: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0",
        comment="Wall-clock parse time (ms)",
    )
    symbol_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    import_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    call_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    function_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    class_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    route_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    __table_args__ = (
        Index("ix_file_parse_jobs_repo_status", "repository_id", "parse_status"),
    )

    def __repr__(self) -> str:
        return (
            f"<FileParseJob file_id={self.file_id} "
            f"status={self.parse_status.value}>"
        )


# ── Symbol ─────────────────────────────────────────────────────────────────────

class Symbol(Base, AuditMixin):
    """A named code symbol extracted from a source file.

    Attributes:
        repository_id: Owning repository UUID.
        file_id: Source file UUID.
        symbol_name: Short unqualified name.
        qualified_name: Fully qualified symbol name.
        symbol_type: Symbol classification enum.
        visibility: Access level.
        start_line: 1-indexed start line.
        end_line: 1-indexed end line.
        language: Source language.
        parent_symbol: Qualified name of enclosing symbol.
        documentation: Extracted docstring text.
        signature: Human-readable signature.
    """

    __tablename__ = "symbols"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    symbol_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    qualified_name: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    symbol_type: Mapped[SymbolType] = mapped_column(
        Enum(SymbolType, name="symbol_type", create_type=True),
        nullable=False, index=True,
    )
    visibility: Mapped[Visibility] = mapped_column(
        Enum(Visibility, name="visibility", create_type=True),
        nullable=False, default=Visibility.UNKNOWN,
    )
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parent_symbol: Mapped[str | None] = mapped_column(String(1024), nullable=True, index=True)
    documentation: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_symbols_repo_file", "repository_id", "file_id"),
        Index("ix_symbols_repo_type", "repository_id", "symbol_type"),
        Index("ix_symbols_qualified_name", "qualified_name"),
    )

    def __repr__(self) -> str:
        return (
            f"<Symbol {self.symbol_type.value} "
            f"qualified_name={self.qualified_name!r}>"
        )


# ── Import ─────────────────────────────────────────────────────────────────────

class ImportRecord(Base, AuditMixin):
    """An import/require/use statement extracted from a source file."""

    __tablename__ = "imports"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    module_path: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    imported_names: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON array of imported names",
    )
    alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_relative: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_imports_repo_module", "repository_id", "module_path"),
    )


# ── Call ───────────────────────────────────────────────────────────────────────

class CallRecord(Base, AuditMixin):
    """A function or method call extracted from source code."""

    __tablename__ = "calls"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    caller_name: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    callee_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    callee_object: Mapped[str | None] = mapped_column(String(512), nullable=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_calls_caller_callee", "caller_name", "callee_name"),
        Index("ix_calls_repo_file", "repository_id", "file_id"),
    )


# ── Route ──────────────────────────────────────────────────────────────────────

class RouteRecord(Base, AuditMixin):
    """An HTTP route/endpoint detected in source code."""

    __tablename__ = "routes"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    http_method: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    handler_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    framework: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_routes_repo_method_path", "repository_id", "http_method", "path"),
    )


# ── Class ──────────────────────────────────────────────────────────────────────

class ClassRecord(Base, AuditMixin):
    """A class definition with inheritance and member metadata."""

    __tablename__ = "classes"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    class_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    qualified_name: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    base_classes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON array")
    interfaces: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON array")
    visibility: Mapped[Visibility] = mapped_column(
        Enum(Visibility, name="visibility", create_type=False),
        nullable=False, default=Visibility.PUBLIC,
    )
    is_abstract: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    documentation: Mapped[str | None] = mapped_column(Text, nullable=True)
    decorators: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON array")

    __table_args__ = (
        Index("ix_classes_repo_name", "repository_id", "class_name"),
    )


# ── Function ───────────────────────────────────────────────────────────────────

class FunctionRecord(Base, AuditMixin):
    """A function or method definition with full signature metadata."""

    __tablename__ = "functions"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repository_files.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    function_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    qualified_name: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    is_method: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_constructor: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_async: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_static: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_class_method: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    visibility: Mapped[Visibility] = mapped_column(
        Enum(Visibility, name="visibility", create_type=False),
        nullable=False, default=Visibility.PUBLIC,
    )
    parameters: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON array")
    return_type: Mapped[str | None] = mapped_column(String(512), nullable=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    documentation: Mapped[str | None] = mapped_column(Text, nullable=True)
    decorators: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON array")
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_functions_repo_name", "repository_id", "function_name"),
        Index("ix_functions_repo_file", "repository_id", "file_id"),
    )
