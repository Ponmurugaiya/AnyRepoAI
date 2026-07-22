"""Create repository_files table.

Revision ID: 002_create_repository_files
Revises: 001_create_repositories
Create Date: 2024-01-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic
revision: str = "002_create_repository_files"
down_revision: str | None = "001_create_repositories"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create repository_files table and supporting enum types."""

    # Create file_status enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE file_status AS ENUM (
                'PENDING', 'SCANNED', 'FAILED', 'IGNORED'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # Create programming_language enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE programming_language AS ENUM (
                'Python', 'Java', 'JavaScript', 'TypeScript', 'Go',
                'C', 'C++', 'Rust', 'Kotlin', 'Swift', 'PHP', 'Ruby',
                'Markdown', 'JSON', 'YAML', 'Dockerfile', 'Terraform',
                'Shell', 'HTML', 'CSS', 'SQL', 'Unknown'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
    """)

    op.create_table(
        "repository_files",

        # ── Primary key ───────────────────────────────────────────────────────
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment="Primary key UUID",
        ),

        # ── Foreign key ───────────────────────────────────────────────────────
        sa.Column(
            "repository_id",
            UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
            comment="FK to the parent repository",
        ),

        # ── Path fields ───────────────────────────────────────────────────────
        sa.Column(
            "relative_path",
            sa.String(length=4096),
            nullable=False,
            comment="Path relative to repository root (POSIX separators)",
        ),
        sa.Column(
            "absolute_path",
            sa.String(length=4096),
            nullable=False,
            comment="Absolute filesystem path to the file",
        ),
        sa.Column(
            "file_name",
            sa.String(length=512),
            nullable=False,
            comment="Base name of the file including extension",
        ),
        sa.Column(
            "extension",
            sa.String(length=64),
            nullable=False,
            server_default="",
            comment="File extension without leading dot; empty when absent",
        ),

        # ── Language / type detection ─────────────────────────────────────────
        sa.Column(
            "language",
            sa.String(length=64),
            nullable=False,
            server_default="Unknown",
            comment="Detected programming language",
        ),
        sa.Column(
            "mime_type",
            sa.String(length=128),
            nullable=False,
            server_default="application/octet-stream",
            comment="MIME type string",
        ),

        # ── File attributes ───────────────────────────────────────────────────
        sa.Column(
            "size_bytes",
            sa.BigInteger,
            nullable=False,
            server_default="0",
            comment="File size in bytes",
        ),
        sa.Column(
            "sha256",
            sa.String(length=64),
            nullable=True,
            comment="SHA-256 hex digest of file contents; NULL for binary/ignored files",
        ),
        sa.Column(
            "is_binary",
            sa.Boolean,
            nullable=False,
            server_default="false",
            comment="True when the file is detected as binary",
        ),
        sa.Column(
            "is_hidden",
            sa.Boolean,
            nullable=False,
            server_default="false",
            comment="True when the file or a parent directory name begins with a dot",
        ),
        sa.Column(
            "last_modified",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Filesystem last-modification timestamp (UTC)",
        ),

        # ── Scan lifecycle ────────────────────────────────────────────────────
        sa.Column(
            "scan_status",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
            comment="Scan lifecycle status of this file",
        ),

        # ── Audit timestamps ──────────────────────────────────────────────────
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Record creation timestamp (UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Record last-update timestamp (UTC)",
        ),

        # ── Constraints ───────────────────────────────────────────────────────
        sa.PrimaryKeyConstraint("id"),
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    op.create_index(
        "ix_repository_files_repository_id",
        "repository_files",
        ["repository_id"],
    )
    op.create_index(
        "ix_repository_files_file_name",
        "repository_files",
        ["file_name"],
    )
    op.create_index(
        "ix_repository_files_extension",
        "repository_files",
        ["extension"],
    )
    op.create_index(
        "ix_repository_files_language",
        "repository_files",
        ["language"],
    )
    op.create_index(
        "ix_repository_files_scan_status",
        "repository_files",
        ["scan_status"],
    )
    op.create_index(
        "ix_repository_files_sha256",
        "repository_files",
        ["sha256"],
    )
    op.create_index(
        "ix_repository_files_repo_rel_path",
        "repository_files",
        ["repository_id", "relative_path"],
        unique=True,
    )
    op.create_index(
        "ix_repository_files_repo_language",
        "repository_files",
        ["repository_id", "language"],
    )

    # ── Cast columns to native enum types ─────────────────────────────────────
    op.execute("ALTER TABLE repository_files ALTER COLUMN scan_status DROP DEFAULT;")
    op.execute("""
        ALTER TABLE repository_files
            ALTER COLUMN scan_status
            TYPE file_status
            USING scan_status::file_status;
    """)
    op.execute(
        "ALTER TABLE repository_files "
        "ALTER COLUMN scan_status SET DEFAULT 'PENDING'::file_status;"
    )

    op.execute("ALTER TABLE repository_files ALTER COLUMN language DROP DEFAULT;")
    op.execute("""
        ALTER TABLE repository_files
            ALTER COLUMN language
            TYPE programming_language
            USING language::programming_language;
    """)
    op.execute(
        "ALTER TABLE repository_files "
        "ALTER COLUMN language SET DEFAULT 'Unknown'::programming_language;"
    )


def downgrade() -> None:
    """Drop the repository_files table and enum types."""
    op.drop_index("ix_repository_files_repo_language", table_name="repository_files")
    op.drop_index("ix_repository_files_repo_rel_path", table_name="repository_files")
    op.drop_index("ix_repository_files_sha256", table_name="repository_files")
    op.drop_index("ix_repository_files_scan_status", table_name="repository_files")
    op.drop_index("ix_repository_files_language", table_name="repository_files")
    op.drop_index("ix_repository_files_extension", table_name="repository_files")
    op.drop_index("ix_repository_files_file_name", table_name="repository_files")
    op.drop_index("ix_repository_files_repository_id", table_name="repository_files")
    op.drop_table("repository_files")

    sa.Enum(name="file_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="programming_language").drop(op.get_bind(), checkfirst=True)
