"""Create Code Intelligence Engine tables.

Revision ID: 003_create_intelligence_tables
Revises: 002_create_repository_files
Create Date: 2025-07-22 00:00:00.000000

Creates:
    - file_parse_jobs    (parse lifecycle tracking)
    - symbols            (all named code symbols)
    - imports            (import statements)
    - calls              (function call references)
    - routes             (HTTP route definitions)
    - classes            (class definitions)
    - functions          (function/method definitions)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "003_create_intelligence_tables"
down_revision: str | None = "002_create_repository_files"
branch_labels: str | None = None
depends_on: str | None = None


def _create_enum(name: str, values: list[str]) -> None:
    """Create a PostgreSQL enum type if it does not already exist."""
    vals = ", ".join(f"'{v}'" for v in values)
    op.execute(f"""
        DO $$ BEGIN
            CREATE TYPE {name} AS ENUM ({vals});
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
    """)


def upgrade() -> None:
    """Create all Code Intelligence Engine tables."""

    # ── Enums ──────────────────────────────────────────────────────────────────
    _create_enum("parse_status", ["QUEUED", "PARSING", "COMPLETED", "FAILED"])
    _create_enum("symbol_type", [
        "class", "function", "method", "constructor",
        "variable", "constant", "enum", "interface",
        "struct", "module", "package", "route",
        "decorator", "annotation",
    ])
    _create_enum("visibility", ["public", "private", "protected", "internal", "unknown"])

    # ── file_parse_jobs ────────────────────────────────────────────────────────
    op.create_table(
        "file_parse_jobs",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("file_id", UUID(as_uuid=True), sa.ForeignKey("repository_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repository_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parse_status", sa.String(16), nullable=False, server_default="QUEUED"),
        sa.Column("language", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("parse_duration_ms", sa.Float, nullable=False, server_default="0"),
        sa.Column("symbol_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("import_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("call_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("function_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("class_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("route_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id", name="uq_file_parse_jobs_file_id"),
    )
    op.create_index("ix_file_parse_jobs_file_id", "file_parse_jobs", ["file_id"])
    op.create_index("ix_file_parse_jobs_repository_id", "file_parse_jobs", ["repository_id"])
    op.create_index("ix_file_parse_jobs_repo_status", "file_parse_jobs", ["repository_id", "parse_status"])

    # Cast to enum
    op.execute("ALTER TABLE file_parse_jobs ALTER COLUMN parse_status DROP DEFAULT;")
    op.execute("ALTER TABLE file_parse_jobs ALTER COLUMN parse_status TYPE parse_status USING parse_status::parse_status;")
    op.execute("ALTER TABLE file_parse_jobs ALTER COLUMN parse_status SET DEFAULT 'QUEUED'::parse_status;")

    # ── symbols ────────────────────────────────────────────────────────────────
    op.create_table(
        "symbols",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("repository_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", UUID(as_uuid=True), sa.ForeignKey("repository_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol_name", sa.String(512), nullable=False),
        sa.Column("qualified_name", sa.String(1024), nullable=False),
        sa.Column("symbol_type", sa.String(32), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("start_line", sa.Integer, nullable=False),
        sa.Column("end_line", sa.Integer, nullable=False),
        sa.Column("language", sa.String(64), nullable=False),
        sa.Column("parent_symbol", sa.String(1024), nullable=True),
        sa.Column("documentation", sa.Text, nullable=True),
        sa.Column("signature", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_symbols_repository_id", "symbols", ["repository_id"])
    op.create_index("ix_symbols_file_id", "symbols", ["file_id"])
    op.create_index("ix_symbols_symbol_name", "symbols", ["symbol_name"])
    op.create_index("ix_symbols_qualified_name", "symbols", ["qualified_name"])
    op.create_index("ix_symbols_symbol_type", "symbols", ["symbol_type"])
    op.create_index("ix_symbols_language", "symbols", ["language"])
    op.create_index("ix_symbols_parent_symbol", "symbols", ["parent_symbol"])
    op.create_index("ix_symbols_repo_file", "symbols", ["repository_id", "file_id"])
    op.create_index("ix_symbols_repo_type", "symbols", ["repository_id", "symbol_type"])

    op.execute("ALTER TABLE symbols ALTER COLUMN symbol_type TYPE symbol_type USING symbol_type::symbol_type;")
    op.execute("ALTER TABLE symbols ALTER COLUMN visibility DROP DEFAULT;")
    op.execute("ALTER TABLE symbols ALTER COLUMN visibility TYPE visibility USING visibility::visibility;")
    op.execute("ALTER TABLE symbols ALTER COLUMN visibility SET DEFAULT 'unknown'::visibility;")

    # ── imports ────────────────────────────────────────────────────────────────
    op.create_table(
        "imports",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("repository_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", UUID(as_uuid=True), sa.ForeignKey("repository_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module_path", sa.String(2048), nullable=False),
        sa.Column("imported_names", sa.Text, nullable=True),
        sa.Column("alias", sa.String(255), nullable=True),
        sa.Column("is_relative", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("start_line", sa.Integer, nullable=False),
        sa.Column("language", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_imports_repository_id", "imports", ["repository_id"])
    op.create_index("ix_imports_file_id", "imports", ["file_id"])
    op.create_index("ix_imports_module_path", "imports", ["module_path"])
    op.create_index("ix_imports_repo_module", "imports", ["repository_id", "module_path"])

    # ── calls ──────────────────────────────────────────────────────────────────
    op.create_table(
        "calls",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("repository_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", UUID(as_uuid=True), sa.ForeignKey("repository_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("caller_name", sa.String(1024), nullable=False),
        sa.Column("callee_name", sa.String(512), nullable=False),
        sa.Column("callee_object", sa.String(512), nullable=True),
        sa.Column("start_line", sa.Integer, nullable=False),
        sa.Column("language", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calls_repository_id", "calls", ["repository_id"])
    op.create_index("ix_calls_file_id", "calls", ["file_id"])
    op.create_index("ix_calls_caller_name", "calls", ["caller_name"])
    op.create_index("ix_calls_callee_name", "calls", ["callee_name"])
    op.create_index("ix_calls_repo_file", "calls", ["repository_id", "file_id"])
    op.create_index("ix_calls_caller_callee", "calls", ["caller_name", "callee_name"])

    # ── routes ─────────────────────────────────────────────────────────────────
    op.create_table(
        "routes",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("repository_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", UUID(as_uuid=True), sa.ForeignKey("repository_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("http_method", sa.String(16), nullable=False),
        sa.Column("path", sa.String(2048), nullable=False),
        sa.Column("handler_name", sa.String(1024), nullable=False),
        sa.Column("framework", sa.String(64), nullable=False),
        sa.Column("start_line", sa.Integer, nullable=False),
        sa.Column("language", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_routes_repository_id", "routes", ["repository_id"])
    op.create_index("ix_routes_file_id", "routes", ["file_id"])
    op.create_index("ix_routes_http_method", "routes", ["http_method"])
    op.create_index("ix_routes_path", "routes", ["path"])
    op.create_index("ix_routes_framework", "routes", ["framework"])
    op.create_index("ix_routes_repo_method_path", "routes", ["repository_id", "http_method", "path"])

    # ── classes ────────────────────────────────────────────────────────────────
    op.create_table(
        "classes",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("repository_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", UUID(as_uuid=True), sa.ForeignKey("repository_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_name", sa.String(512), nullable=False),
        sa.Column("qualified_name", sa.String(1024), nullable=False),
        sa.Column("base_classes", sa.Text, nullable=True),
        sa.Column("interfaces", sa.Text, nullable=True),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="public"),
        sa.Column("is_abstract", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("start_line", sa.Integer, nullable=False),
        sa.Column("end_line", sa.Integer, nullable=False),
        sa.Column("language", sa.String(64), nullable=False),
        sa.Column("documentation", sa.Text, nullable=True),
        sa.Column("decorators", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_classes_repository_id", "classes", ["repository_id"])
    op.create_index("ix_classes_file_id", "classes", ["file_id"])
    op.create_index("ix_classes_class_name", "classes", ["class_name"])
    op.create_index("ix_classes_qualified_name", "classes", ["qualified_name"])
    op.create_index("ix_classes_language", "classes", ["language"])
    op.create_index("ix_classes_repo_name", "classes", ["repository_id", "class_name"])

    op.execute("ALTER TABLE classes ALTER COLUMN visibility DROP DEFAULT;")
    op.execute("ALTER TABLE classes ALTER COLUMN visibility TYPE visibility USING visibility::visibility;")
    op.execute("ALTER TABLE classes ALTER COLUMN visibility SET DEFAULT 'public'::visibility;")

    # ── functions ──────────────────────────────────────────────────────────────
    op.create_table(
        "functions",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("repository_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", UUID(as_uuid=True), sa.ForeignKey("repository_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("function_name", sa.String(512), nullable=False),
        sa.Column("qualified_name", sa.String(1024), nullable=False),
        sa.Column("is_method", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_constructor", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_async", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_static", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_class_method", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="public"),
        sa.Column("parameters", sa.Text, nullable=True),
        sa.Column("return_type", sa.String(512), nullable=True),
        sa.Column("start_line", sa.Integer, nullable=False),
        sa.Column("end_line", sa.Integer, nullable=False),
        sa.Column("language", sa.String(64), nullable=False),
        sa.Column("documentation", sa.Text, nullable=True),
        sa.Column("decorators", sa.Text, nullable=True),
        sa.Column("signature", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_functions_repository_id", "functions", ["repository_id"])
    op.create_index("ix_functions_file_id", "functions", ["file_id"])
    op.create_index("ix_functions_function_name", "functions", ["function_name"])
    op.create_index("ix_functions_qualified_name", "functions", ["qualified_name"])
    op.create_index("ix_functions_language", "functions", ["language"])
    op.create_index("ix_functions_repo_name", "functions", ["repository_id", "function_name"])
    op.create_index("ix_functions_repo_file", "functions", ["repository_id", "file_id"])

    op.execute("ALTER TABLE functions ALTER COLUMN visibility DROP DEFAULT;")
    op.execute("ALTER TABLE functions ALTER COLUMN visibility TYPE visibility USING visibility::visibility;")
    op.execute("ALTER TABLE functions ALTER COLUMN visibility SET DEFAULT 'public'::visibility;")


def downgrade() -> None:
    """Drop all Code Intelligence Engine tables and enums."""
    for table in ("functions", "classes", "routes", "calls", "imports", "symbols", "file_parse_jobs"):
        op.drop_table(table)
    for enum_name in ("parse_status", "symbol_type", "visibility"):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
