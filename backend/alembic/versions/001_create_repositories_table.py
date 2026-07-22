"""Create repositories table.

Revision ID: 001_create_repositories
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic
revision: str = "001_create_repositories"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the repositories table and supporting enum type."""

    # Use DO block to create the enum only if it doesn't exist.
    # This is more reliable than postgresql.ENUM(...).create(checkfirst=True)
    # which can fail inside a transaction on some psycopg2 versions.
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE repository_status AS ENUM (
                'PENDING', 'CLONING', 'READY', 'FAILED', 'SYNCING'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
    """)

    op.create_table(
        "repositories",
        # ── Primary key ──────────────────────────────────────────────────────
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment="Primary key UUID",
        ),

        # ── Identity ─────────────────────────────────────────────────────────
        sa.Column(
            "owner",
            sa.String(length=255),
            nullable=False,
            comment="GitHub repository owner (user or organisation)",
        ),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
            comment="Repository name without owner prefix",
        ),
        sa.Column(
            "full_name",
            sa.String(length=512),
            nullable=False,
            comment="Canonical owner/name identifier (unique)",
        ),
        sa.Column(
            "github_url",
            sa.String(length=512),
            nullable=False,
            comment="Normalised HTTPS clone URL (no trailing .git)",
        ),

        # ── Clone state ───────────────────────────────────────────────────────
        sa.Column(
            "default_branch",
            sa.String(length=255),
            nullable=True,
            comment="Primary branch name, populated after clone",
        ),
        sa.Column(
            "local_path",
            sa.String(length=1024),
            nullable=True,
            comment="Absolute filesystem path to the local clone",
        ),
        sa.Column(
            "current_commit",
            sa.String(length=40),
            nullable=True,
            comment="HEAD commit SHA of the local clone",
        ),
        sa.Column(
            "clone_status",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
            comment="Current lifecycle status of the repository",
        ),

        # ── GitHub metadata ───────────────────────────────────────────────────
        sa.Column(
            "description",
            sa.Text,
            nullable=True,
            comment="Repository description from GitHub API",
        ),
        sa.Column(
            "visibility",
            sa.String(length=16),
            nullable=True,
            comment="public or private",
        ),
        sa.Column(
            "language",
            sa.String(length=100),
            nullable=True,
            comment="Primary programming language reported by GitHub",
        ),
        sa.Column(
            "stars",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="Stargazer count at last sync",
        ),
        sa.Column(
            "forks",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="Fork count at last sync",
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
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of the last successful metadata sync",
        ),

        # ── Constraints ───────────────────────────────────────────────────────
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("full_name", name="uq_repositories_full_name"),
        sa.UniqueConstraint("github_url", name="uq_repositories_github_url"),
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    op.create_index("ix_repositories_owner", "repositories", ["owner"])
    op.create_index("ix_repositories_name", "repositories", ["name"])
    op.create_index("ix_repositories_full_name", "repositories", ["full_name"])
    op.create_index("ix_repositories_github_url", "repositories", ["github_url"])
    op.create_index("ix_repositories_clone_status", "repositories", ["clone_status"])

    # Cast clone_status column to the native enum type now that both exist.
    # Must drop the text default first, alter the type, then restore the enum default.
    op.execute("ALTER TABLE repositories ALTER COLUMN clone_status DROP DEFAULT;")
    op.execute("""
        ALTER TABLE repositories
            ALTER COLUMN clone_status
            TYPE repository_status
            USING clone_status::repository_status;
    """)
    op.execute("ALTER TABLE repositories ALTER COLUMN clone_status SET DEFAULT 'PENDING'::repository_status;")


def downgrade() -> None:
    """Drop the repositories table and the repository_status enum."""
    op.drop_index("ix_repositories_clone_status", table_name="repositories")
    op.drop_index("ix_repositories_github_url", table_name="repositories")
    op.drop_index("ix_repositories_full_name", table_name="repositories")
    op.drop_index("ix_repositories_name", table_name="repositories")
    op.drop_index("ix_repositories_owner", table_name="repositories")
    op.drop_table("repositories")

    # Drop the enum type
    sa.Enum(name="repository_status").drop(op.get_bind(), checkfirst=True)
