"""Pydantic schemas for the Symbol Intelligence Engine API.

All request/response models for the symbol-index endpoints live here.
They mirror the :class:`~backend.app.symbol_index.models.index.SymbolIndexEntry`
ORM model but are intentionally decoupled so the API surface can evolve
independently of the persistence layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Indexing lifecycle ─────────────────────────────────────────────────────────


class IndexInitiatedResponse(BaseModel):
    """Returned immediately when a symbol-indexing job is enqueued.

    Attributes:
        repository_id: Repository being indexed.
        status: Always ``"QUEUED"`` immediately after enqueue.
        message: Human-readable confirmation.
    """

    repository_id: uuid.UUID = Field(description="Repository being indexed")
    status: str = Field(description="Initial indexing status")
    message: str = Field(description="Human-readable confirmation")


class IndexProgressResponse(BaseModel):
    """Current symbol-index progress for a repository.

    Attributes:
        repository_id: Repository UUID.
        status: Overall status string.
        total_files: Total files to be indexed.
        indexed_files: Files fully indexed.
        failed_files: Files that encountered errors.
        total_symbols: Symbols written to the index so far.
        duplicate_symbols: Symbols skipped due to qualified-name collision.
        index_duration_seconds: Elapsed time when completed.
    """

    repository_id: uuid.UUID = Field(description="Repository UUID")
    status: str = Field(
        description=(
            "Overall status: NOT_STARTED, QUEUED, INDEXING, COMPLETED, "
            "COMPLETED_WITH_ERRORS, FAILED"
        )
    )
    total_files: int = Field(default=0, description="Total files to index")
    indexed_files: int = Field(default=0, description="Files successfully indexed")
    failed_files: int = Field(default=0, description="Files that failed")
    total_symbols: int = Field(default=0, description="Symbols in the index")
    duplicate_symbols: int = Field(default=0, description="Symbols skipped (duplicate QN)")
    index_duration_seconds: float = Field(
        default=0.0, description="Elapsed seconds (when completed)"
    )


class IndexStatistics(BaseModel):
    """Aggregate statistics from a completed indexing run.

    Attributes:
        repository_id: Repository UUID.
        total_files: Files eligible for indexing.
        indexed_files: Files successfully indexed.
        failed_files: Files that failed.
        total_symbols: Total entries written to the index.
        duplicate_symbols: Symbols skipped due to qualified-name collision.
        index_duration_seconds: Wall-clock time for the full run.
    """

    repository_id: uuid.UUID = Field(description="Repository UUID")
    total_files: int = Field(default=0, description="Files eligible for indexing")
    indexed_files: int = Field(default=0, description="Files indexed successfully")
    failed_files: int = Field(default=0, description="Files that failed")
    total_symbols: int = Field(default=0, description="Total symbols indexed")
    duplicate_symbols: int = Field(default=0, description="Symbols skipped (duplicate QN)")
    index_duration_seconds: float = Field(
        default=0.0, description="Wall-clock indexing time (seconds)"
    )


# ── Symbol entry responses ─────────────────────────────────────────────────────


class SymbolIndexEntryResponse(BaseModel):
    """Complete symbol index entry as returned by the API.

    All fields mirror :class:`~backend.app.symbol_index.models.index.SymbolIndexEntry`.
    """

    id: uuid.UUID = Field(description="Symbol entry UUID")
    repository_id: uuid.UUID = Field(description="Owning repository UUID")
    file_id: uuid.UUID = Field(description="Source file UUID")
    language: str = Field(description="Source programming language")
    symbol_type: str = Field(description="Symbol classification")
    name: str = Field(description="Short unqualified name")
    qualified_name: str = Field(description="Fully-qualified name")
    display_name: str = Field(description="Human-readable label")
    parent_symbol_id: uuid.UUID | None = Field(
        default=None, description="Enclosing symbol UUID"
    )
    module_name: str | None = Field(default=None, description="Module path")
    namespace: str | None = Field(default=None, description="Namespace or package")
    signature: str | None = Field(default=None, description="Normalised signature")
    return_type: str | None = Field(default=None, description="Return type annotation")
    visibility: str = Field(description="Access modifier")
    is_static: bool = Field(description="Static flag")
    is_async: bool = Field(description="Async flag")
    is_exported: bool = Field(description="Exported flag")
    is_deprecated: bool = Field(description="Deprecated flag")
    documentation: str | None = Field(default=None, description="Documentation text")
    start_line: int = Field(description="1-indexed start line")
    end_line: int = Field(description="1-indexed end line")
    start_column: int = Field(description="0-indexed start column")
    end_column: int = Field(description="0-indexed end column")
    created_at: datetime = Field(description="Record creation timestamp")
    updated_at: datetime = Field(description="Record last-update timestamp")

    model_config = {"from_attributes": True}


class SymbolIndexListResponse(BaseModel):
    """Paginated list of symbol index entries.

    Attributes:
        items: Page of symbol entries.
        total: Total matching record count.
        limit: Page size.
        offset: Row offset.
    """

    items: list[SymbolIndexEntryResponse] = Field(description="Page of symbols")
    total: int = Field(description="Total matching symbol count")
    limit: int = Field(description="Page size")
    offset: int = Field(description="Row offset")


# ── Search ─────────────────────────────────────────────────────────────────────


class SymbolIndexSearchRequest(BaseModel):
    """Request body for symbol search.

    Attributes:
        query: Search term. May be a prefix, exact name, or qualified name.
        mode: Search mode: ``prefix``, ``exact``, or ``qualified``.
        language: Optional language filter.
        symbol_type: Optional symbol-type filter.
        limit: Maximum results to return.
    """

    query: str = Field(
        min_length=1,
        max_length=512,
        description="Search query (name or qualified name fragment)",
    )
    mode: Literal["prefix", "exact", "qualified"] = Field(
        default="prefix",
        description=(
            "Search mode: "
            "``prefix`` — name starts with query; "
            "``exact`` — exact name match; "
            "``qualified`` — qualified_name contains query."
        ),
    )
    language: str | None = Field(default=None, description="Filter by language")
    symbol_type: str | None = Field(default=None, description="Filter by symbol type")
    limit: int = Field(
        default=50, ge=1, le=500, description="Maximum results to return"
    )


class SymbolIndexSearchResponse(BaseModel):
    """Response envelope for symbol search results.

    Attributes:
        query: The original search query.
        mode: Search mode used.
        items: Matching symbol entries.
        total: Number of matches found.
    """

    query: str = Field(description="Original search query")
    mode: str = Field(description="Search mode used")
    items: list[SymbolIndexEntryResponse] = Field(description="Matching symbols")
    total: int = Field(description="Total matches found")
