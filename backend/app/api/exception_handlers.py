"""Global FastAPI exception handlers.

Maps application exceptions and framework validation errors to the
unified APIResponse envelope so clients always receive a predictable
error shape.
"""

import traceback

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.core.exceptions import AppException
from backend.app.core.logging import get_logger
from backend.app.schemas.base import APIResponse, ErrorDetail

logger = get_logger(__name__)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handle domain-level AppException subclasses.

    Converts structured application errors to the APIResponse envelope.

    Args:
        request: The incoming FastAPI request.
        exc: The caught AppException instance.

    Returns:
        JSONResponse: Serialised APIResponse failure with appropriate status code.
    """
    logger.warning(
        "Application exception",
        error_code=exc.error_code,
        message=exc.message,
        path=request.url.path,
        status_code=exc.status_code,
    )

    errors = (
        [ErrorDetail(message=detail.get("msg", ""), code=exc.error_code, field=detail.get("loc"))
         for detail in exc.details]
        if isinstance(exc.details, list) and exc.details
        else []
    )

    response = APIResponse.fail(message=exc.message, errors=errors)
    return JSONResponse(status_code=exc.status_code, content=response.model_dump())


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Handle standard Starlette / FastAPI HTTP exceptions.

    Args:
        request: The incoming FastAPI request.
        exc: The caught HTTPException instance.

    Returns:
        JSONResponse: Serialised APIResponse failure.
    """
    logger.warning(
        "HTTP exception",
        status_code=exc.status_code,
        detail=exc.detail,
        path=request.url.path,
    )

    response = APIResponse.fail(message=str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content=response.model_dump())


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic v2 request validation errors (422).

    Flattens Pydantic's error list into ErrorDetail items so the
    client can map field-level errors back to the request body.

    Args:
        request: The incoming FastAPI request.
        exc: The RequestValidationError from Pydantic.

    Returns:
        JSONResponse: Serialised APIResponse with per-field error details.
    """
    errors: list[ErrorDetail] = []
    for error in exc.errors():
        field_path = " -> ".join(str(loc) for loc in error.get("loc", []))
        errors.append(
            ErrorDetail(
                field=field_path or None,
                message=error.get("msg", "Validation error"),
                code=error.get("type", "VALIDATION_ERROR").upper(),
            )
        )

    logger.info(
        "Request validation failed",
        path=request.url.path,
        error_count=len(errors),
    )

    response = APIResponse.fail(
        message="Request validation failed. Check the errors field for details.",
        errors=errors,
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=response.model_dump(),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unexpected exceptions.

    Logs the full traceback at ERROR level but returns only a generic
    message to the client to avoid leaking implementation details.

    Args:
        request: The incoming FastAPI request.
        exc: The unhandled exception.

    Returns:
        JSONResponse: Generic 500 APIResponse failure.
    """
    logger.error(
        "Unhandled exception",
        path=request.url.path,
        exc_type=type(exc).__name__,
        traceback=traceback.format_exc(),
    )

    response = APIResponse.fail(
        message="An unexpected internal error occurred. Please try again later."
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=response.model_dump(),
    )
