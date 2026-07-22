"""Unified API response envelope.

All endpoints must return one of these models so clients receive
a predictable, consistent response shape regardless of the operation.
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class ErrorDetail(BaseModel):
    """A single structured error detail item.

    Attributes:
        field: The field or path where the error occurred (optional).
        message: Human-readable error description.
        code: Machine-readable error code for programmatic handling.
    """

    field: str | None = Field(default=None, description="Field path that caused the error")
    message: str = Field(description="Human-readable error description")
    code: str = Field(description="Machine-readable error code")


class APIResponse(BaseModel, Generic[DataT]):
    """Unified response envelope for all API endpoints.

    Attributes:
        success: Whether the operation completed successfully.
        data: The response payload (present when success=True).
        message: A human-readable summary of the result.
        errors: List of structured errors (present when success=False).

    Example::

        # Success
        {
            "success": true,
            "data": {"id": "01J..."},
            "message": "Repository created successfully.",
            "errors": []
        }

        # Failure
        {
            "success": false,
            "data": null,
            "message": "Validation failed.",
            "errors": [{"field": "url", "message": "Invalid URL", "code": "INVALID_URL"}]
        }
    """

    success: bool = Field(description="Indicates whether the request succeeded")
    data: DataT | None = Field(default=None, description="Response payload")
    message: str = Field(default="", description="Human-readable result summary")
    errors: list[ErrorDetail] = Field(default_factory=list, description="List of error details")

    @classmethod
    def ok(cls, data: DataT | None = None, message: str = "Success") -> "APIResponse[DataT]":
        """Create a successful response.

        Args:
            data: The response payload.
            message: Summary message.

        Returns:
            APIResponse: A success envelope.
        """
        return cls(success=True, data=data, message=message, errors=[])

    @classmethod
    def fail(
        cls,
        message: str,
        errors: list[ErrorDetail] | None = None,
    ) -> "APIResponse[None]":
        """Create a failure response.

        Args:
            message: High-level error summary.
            errors: Optional list of structured error details.

        Returns:
            APIResponse: A failure envelope.
        """
        return cls(
            success=False,
            data=None,
            message=message,
            errors=errors or [],
        )


class PaginatedData(BaseModel, Generic[DataT]):
    """Paginated list wrapper for collection responses.

    Attributes:
        items: The page of results.
        total: Total number of matching records.
        page: Current page number (1-indexed).
        page_size: Number of items per page.
        total_pages: Total number of pages.
    """

    items: list[DataT] = Field(description="Page of results")
    total: int = Field(description="Total matching record count")
    page: int = Field(description="Current page (1-indexed)")
    page_size: int = Field(description="Items per page")
    total_pages: int = Field(description="Total available pages")
