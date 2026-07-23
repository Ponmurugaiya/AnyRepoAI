"""Pydantic schemas for the Code Intelligence Engine API.

Defines all request/response models for the parser endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ParseInitiatedResponse(BaseModel):
    """Returned immediately when a parse job is enqueued.

    Attributes:
        repository_id: The repository being parsed.
        status: Always ``"QUEUED"`` on initial enqueue.
        message: Human-readable confirmation.
    """

    repository_id: uuid.UUID = Field(description="Repository being parsed")
    status: str = Field(description="Parse lifecycle status")
    message: str = Field(description="Human-readable confirmation")


class ParseStatistics(BaseModel):
    """Aggregate statistics from a completed repository parse.

    Attributes:
        repository_id: Repository UUID.
        total_files: Total files eligible for parsing.
        completed_files: Files parsed without fatal errors.
        failed_files: Files that failed to parse.
        total_symbols: Total symbols extracted across all files.
        total_imports: Total import statements extracted.
        total_calls: Total call references extracted.
        total_functions: Total function definitions extracted.
        total_classes: Total class definitions extracted.
        total_routes: Total HTTP routes detected.
        parse_duration_seconds: Wall-clock time for the full parse run.
    """

    repository_id: uuid.UUID = Field(description="Repository UUID")
    total_files: int = Field(default=0, description="Files eligible for parsing")
    completed_files: int = Field(default=0, description="Files parsed successfully")
    failed_files: int = Field(default=0, description="Files that failed to parse")
    total_symbols: int = Field(default=0, description="Total symbols extracted")
    total_imports: int = Field(default=0, description="Total imports extracted")
    total_calls: int = Field(default=0, description="Total calls extracted")
    total_functions: int = Field(default=0, description="Total functions extracted")
    total_classes: int = Field(default=0, description="Total classes extracted")
    total_routes: int = Field(default=0, description="Total routes detected")
    parse_duration_seconds: float = Field(
        default=0.0, description="Wall-clock time for full parse (seconds)"
    )


class ParseProgressResponse(BaseModel):
    """Current parse progress for a repository.

    Attributes:
        repository_id: Repository UUID.
        status: Overall status string.
        total_files: Total parse job records.
        queued: Files waiting to be parsed.
        parsing: Files currently being parsed.
        completed: Files parsed successfully.
        failed: Files that failed.
    """

    repository_id: uuid.UUID = Field(description="Repository UUID")
    status: str = Field(
        description="Overall status: NOT_STARTED, QUEUED, PARSING, COMPLETED, COMPLETED_WITH_ERRORS"
    )
    total_files: int = Field(default=0)
    queued: int = Field(default=0)
    parsing: int = Field(default=0)
    completed: int = Field(default=0)
    failed: int = Field(default=0)


class SymbolResponse(BaseModel):
    """A single code symbol returned by the API.

    Attributes mirror the :class:`~backend.app.models.symbol.Symbol` ORM model.
    """

    id: uuid.UUID
    repository_id: uuid.UUID
    file_id: uuid.UUID
    symbol_name: str
    qualified_name: str
    symbol_type: str
    visibility: str
    start_line: int
    end_line: int
    language: str
    parent_symbol: str | None = None
    documentation: str | None = None
    signature: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ClassResponse(BaseModel):
    """A class definition returned by the API."""

    id: uuid.UUID
    repository_id: uuid.UUID
    file_id: uuid.UUID
    class_name: str
    qualified_name: str
    base_classes: str | None = None
    interfaces: str | None = None
    visibility: str
    is_abstract: bool
    start_line: int
    end_line: int
    language: str
    documentation: str | None = None
    decorators: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FunctionResponse(BaseModel):
    """A function or method definition returned by the API."""

    id: uuid.UUID
    repository_id: uuid.UUID
    file_id: uuid.UUID
    function_name: str
    qualified_name: str
    is_method: bool
    is_constructor: bool
    is_async: bool
    is_static: bool
    is_class_method: bool
    visibility: str
    parameters: str | None = None
    return_type: str | None = None
    start_line: int
    end_line: int
    language: str
    documentation: str | None = None
    decorators: str | None = None
    signature: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RouteResponse(BaseModel):
    """An HTTP route definition returned by the API."""

    id: uuid.UUID
    repository_id: uuid.UUID
    file_id: uuid.UUID
    http_method: str
    path: str
    handler_name: str
    framework: str
    start_line: int
    language: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SymbolListResponse(BaseModel):
    """Paginated symbol list response."""

    items: list[SymbolResponse]
    total: int
    limit: int
    offset: int


class ClassListResponse(BaseModel):
    """Paginated class list response."""

    items: list[ClassResponse]
    total: int
    limit: int
    offset: int


class FunctionListResponse(BaseModel):
    """Paginated function list response."""

    items: list[FunctionResponse]
    total: int
    limit: int
    offset: int


class RouteListResponse(BaseModel):
    """Paginated route list response."""

    items: list[RouteResponse]
    total: int
    limit: int
    offset: int
