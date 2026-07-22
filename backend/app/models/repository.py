"""Repository ORM model.

Represents a GitHub repository registered in the platform.
Stores both the GitHub metadata and local clone state.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import AuditMixin, Base


class RepositoryStatus(str, enum.Enum):
    """Lifecycle states for a cloned repository.

    Transitions::

        PENDING → CLONING → READY
                          ↘ FAILED
        READY   → SYNCING → READY
                          ↘ FAILED
    """

    PENDING = "PENDING"
    CLONING = "CLONING"
    READY = "READY"
    FAILED = "FAILED"
    SYNCING = "SYNCING"


class Repository(Base, AuditMixin):
    """SQLAlchemy ORM model for GitHub repositories.

    Inherits ``id`` (UUID PK), ``created_at``, and ``updated_at``
    from :class:`~backend.app.db.base.AuditMixin`.

    Attributes:
        owner: GitHub repository owner (user or organisation).
        name: Repository name (without owner prefix).
        full_name: Canonical ``owner/name`` identifier.
        github_url: Normalised HTTPS URL (no trailing ``.git``).
        default_branch: Primary branch name (e.g. ``main``).
        local_path: Absolute filesystem path to the local clone.
        current_commit: HEAD commit SHA of the local clone.
        description: Repository description sourced from GitHub API.
        visibility: ``"public"`` or ``"private"``.
        language: Primary programming language reported by GitHub.
        stars: Star count at last metadata sync.
        forks: Fork count at last metadata sync.
        clone_status: Current lifecycle status of this repository.
        last_synced_at: Timestamp of the last successful metadata sync.
    """

    __tablename__ = "repositories"

    # ── Identity ──────────────────────────────────────────────────────────────
    owner: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="GitHub repository owner (user or organisation)",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Repository name without owner prefix",
    )
    full_name: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        unique=True,
        index=True,
        comment="Canonical owner/name identifier (unique)",
    )
    github_url: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        unique=True,
        index=True,
        comment="Normalised HTTPS clone URL (no trailing .git)",
    )

    # ── Clone state ───────────────────────────────────────────────────────────
    default_branch: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Primary branch name, populated after clone",
    )
    local_path: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="Absolute filesystem path to the local clone",
    )
    current_commit: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        comment="HEAD commit SHA of the local clone",
    )
    clone_status: Mapped[RepositoryStatus] = mapped_column(
        Enum(RepositoryStatus, name="repository_status", create_type=True),
        nullable=False,
        default=RepositoryStatus.PENDING,
        server_default=RepositoryStatus.PENDING.value,
        index=True,
        comment="Current lifecycle status of the repository",
    )

    # ── GitHub metadata ───────────────────────────────────────────────────────
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Repository description from GitHub API",
    )
    visibility: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="public or private",
    )
    language: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Primary programming language reported by GitHub",
    )
    stars: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Stargazer count at last sync",
    )
    forks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Fork count at last sync",
    )

    # ── Audit ─────────────────────────────────────────────────────────────────
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the last successful metadata sync",
    )

    def __repr__(self) -> str:
        return (
            f"<Repository id={self.id} full_name={self.full_name!r} "
            f"status={self.clone_status.value}>"
        )
