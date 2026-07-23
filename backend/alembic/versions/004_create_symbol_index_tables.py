"""Create Symbol Index tables.

Revision ID: 004_create_symbol_index_tables
Revises: 003_create_intelligence_tables
Create Date: 2025-07-23 00:00:00.000000

Creates:
    - symbol_index_jobs         (lifecycle tracking for the Symbol Index)
    - symbol_index_entries      (canonical symbol index)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "004_create_symbol_index_tables"
down_revision: str | None = "003_create_intelligence_tables"
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
    """Create all Symbol Index tables."""

    # ── Enums ──────────────────────────────────────────────────────────────────
    _create_enum("index_status", ["QUEUED", "INDEXING", "COMPLETED", "FAILED"])

    # ── symbol_index_jobs ──────────────────────────────────────────────────────
    op.create_table(
        "symbol_index_jobs",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("repository_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="QUEUED"),
        sa.Column("total_files", sa.Integer, nullable=False, server_default="0"),
        sa.Column("indexed_files", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_files", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_symbols", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duplicate_symbols", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("index_duration_seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repository_id", name="uq_symbol_index_jobs_repository_id"),
    )
    op.create_index("ix_symbol_index_jobs_repository_id", "symbol_index_jobs", ["repository_id"])
    op.create_index("ix_symbol_index_jobs_repo_status", "symbol_index_jobs", ["repository_id", "status"])

    # Cast to enum
    op.execute("ALTER TABLE symbol_index_jobs ALTER COLUMN status DROP DEFAULT;")
    op.execute("ALTER TABLE symbol_index_jobs ALTER COLUMN status TYPE index_status USING status::index_status;")
    op.execute("ALTER TABLE symbol_index_jobs ALTER COLUMN status SET DEFAULT 'QUEUED'::index_status;")

    # ── symbol_index_entries ───────────────────────────────────────────────────
    op.create_table(
        "symbol_index_entries",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("repository_id", UUID(as_uuid=True), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", UUID(as_uuid=True), sa.ForeignKey("repository_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("language", sa.String(64), nullable=False),
        sa.Column("symbol_type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("qualified_name", sa.String(1024), nullable=False),
        sa.Column("display_name", sa.String(512), nullable=False),
        sa.Column("parent_symbol_id", UUID(as_uuid=True), sa.ForeignKey("symbol_index_entries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("module_name", sa.String(1024), nullable=True),
        sa.Column("namespace", sa.String(512), nullable=True),
        sa.Column("signature", sa.Text, nullable=True),
        sa.Column("return_type", sa.String(512), nullable=True),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("is_static", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_async", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_exported", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_deprecated", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("documentation", sa.Text, nullable=True),
        sa.Column("start_line", sa.Integer, nullable=False),
        sa.Column("end_line", sa.Integer, nullable=False),
        sa.Column("start_column", sa.Integer, nullable=False, server_default="0"),
        sa.Column("end_column", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repository_id", "qualified_name", name="uq_symbol_index_repo_qualified_name"),
    )

    op.create_index("ix_sie_repo_id", "symbol_index_entries", ["repository_id"])
    op.create_index("ix_sie_file_id", "symbol_index_entries", ["file_id"])
    op.create_index("ix_sie_language", "symbol_index_entries", ["language"])
    op.create_index("ix_sie_symbol_type", "symbol_index_entries", ["symbol_type"])
    op.create_index("ix_sie_name", "symbol_index_entries", ["name"])
    op.create_index("ix_sie_qualified_name", "symbol_index_entries", ["qualified_name"])
    op.create_index("ix_sie_parent_symbol_id", "symbol_index_entries", ["parent_symbol_id"])
    op.create_index("ix_sie_repo_language", "symbol_index_entries", ["repository_id", "language"])
    op.create_index("ix_sie_repo_type", "symbol_index_entries", ["repository_id", "symbol_type"])
    op.create_index("ix_sie_repo_file", "symbol_index_entries", ["repository_id", "file_id"])
    op.create_index("ix_sie_repo_name", "symbol_index_entries", ["repository_id", "name"])


def downgrade() -> None:
    """Drop all Symbol Index tables and enums."""
    op.drop_table("symbol_index_entries")
    op.drop_table("symbol_index_jobs")
    sa.Enum(name="index_status").drop(op.get_bind(), checkfirst=True)
