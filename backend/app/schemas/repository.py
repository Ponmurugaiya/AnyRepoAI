"""Pydantic schemas for the Repository Management module.

Defines request bodies, response models, and internal data-transfer objects
for the repository lifecycle: create, read, list, and delete.
"""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.models.repository import RepositoryStatus

# ── Accepted URL pattern ──────────────────────────────────────────────────────
# Accepts:
#   https://github.com/owner/repository
#   https://github.com/owner/repository.git
_GITHUB_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.\-]+)/(?P<name>[A-Za-z0-9_.\-]+?)(?:\.git)?$"
)


class RepositoryCreateRequest(BaseModel):
    """Request body for POST /repositories.

    Attributes:
        github_url: A valid GitHub HTTPS repository URL.
        reclone: When ``True``, forces re-clone of an already-registered
                 repository (deletes existing clone and restarts the
                 cloning pipeline).
    """

    github_url: str = Field(
        ...,
        description=(
            "GitHub repository URL. "
            "Accepted formats: https://github.com/owner/repo or "
            "https://github.com/owner/repo.git"
        ),
        examples=["https://github.com/owner/repository"],
    )
    reclone: bool = Field(
        default=False,
        description="Force re-clone even if the repository is already registered.",
    )

    @field_validator("github_url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        """Reject anything that does not match the accepted GitHub URL pattern."""
        url = v.strip()
        if not _GITHUB_URL_RE.match(url):
            raise ValueError(
                "Invalid GitHub URL. "
                "Accepted formats: https://github.com/owner/repo or "
                "https://github.com/owner/repo.git"
            )
        # Normalise: strip trailing .git
        return url.removesuffix(".git")

    @property
    def parsed_owner(self) -> str:
        """Extract the owner segment from the validated URL."""
        m = _GITHUB_URL_RE.match(self.github_url)
        assert m, "URL must be validated before accessing parsed_owner"
        return m.group("owner")

    @property
    def parsed_name(self) -> str:
        """Extract the repo name segment from the validated URL."""
        m = _GITHUB_URL_RE.match(self.github_url)
        assert m, "URL must be validated before accessing parsed_name"
        return m.group("name")


class RepositoryResponse(BaseModel):
    """Full repository representation returned by GET endpoints.

    Attributes mirror the :class:`~backend.app.models.repository.Repository`
    ORM model fields.
    """

    id: uuid.UUID = Field(description="Repository primary key (UUID)")
    owner: str = Field(description="GitHub repository owner")
    name: str = Field(description="Repository name")
    full_name: str = Field(description="Canonical owner/name identifier")
    github_url: str = Field(description="Normalised HTTPS repository URL")
    default_branch: str | None = Field(default=None, description="Primary branch name")
    local_path: str | None = Field(default=None, description="Absolute path to local clone")
    current_commit: str | None = Field(default=None, description="HEAD commit SHA")
    description: str | None = Field(default=None, description="Repository description")
    visibility: str | None = Field(default=None, description="public or private")
    language: str | None = Field(default=None, description="Primary programming language")
    stars: int = Field(default=0, description="Star count at last sync")
    forks: int = Field(default=0, description="Fork count at last sync")
    clone_status: RepositoryStatus = Field(description="Current clone lifecycle status")
    created_at: datetime = Field(description="Record creation timestamp")
    updated_at: datetime = Field(description="Record last-update timestamp")
    last_synced_at: datetime | None = Field(
        default=None, description="Timestamp of last successful metadata sync"
    )

    model_config = {"from_attributes": True}


class RepositoryCreateResponse(BaseModel):
    """Minimal response returned immediately after POST /repositories.

    The full metadata is populated asynchronously by the background task;
    the caller should poll GET /repositories/{id} for the final state.

    Attributes:
        id: Repository UUID assigned at creation time.
        status: Initial status (always ``PENDING`` on creation).
    """

    id: uuid.UUID = Field(description="Assigned repository UUID")
    status: RepositoryStatus = Field(description="Lifecycle status at time of creation")

    model_config = {"from_attributes": True}


class RepositoryListResponse(BaseModel):
    """Wrapper for the list-all-repositories response payload."""

    items: list[RepositoryResponse] = Field(description="All registered repositories")
    total: int = Field(description="Total number of registered repositories")
