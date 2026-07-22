"""Domain exception hierarchy.

All application-level errors should extend from AppException so the
global exception handler can map them to consistent HTTP responses.
"""

from http import HTTPStatus


class AppException(Exception):
    """Base exception for all application errors.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status code to return.
        error_code: Machine-readable error identifier for clients.
        details: Optional extra context (e.g., field validation errors).
    """

    def __init__(
        self,
        message: str,
        status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR,
        error_code: str = "INTERNAL_ERROR",
        details: dict | list | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or []
        super().__init__(message)


class NotFoundError(AppException):
    """Raised when a requested resource does not exist.

    Args:
        resource: Name of the resource type (e.g., "Repository").
        identifier: The ID or key that was not found.
    """

    def __init__(self, resource: str, identifier: str | int) -> None:
        super().__init__(
            message=f"{resource} with identifier '{identifier}' was not found.",
            status_code=HTTPStatus.NOT_FOUND,
            error_code="NOT_FOUND",
        )


class ValidationError(AppException):
    """Raised when input data fails business-level validation.

    Args:
        message: Description of the validation failure.
        details: List of field-level error dictionaries.
    """

    def __init__(self, message: str, details: list | None = None) -> None:
        super().__init__(
            message=message,
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            error_code="VALIDATION_ERROR",
            details=details or [],
        )


class ConflictError(AppException):
    """Raised when an operation conflicts with existing state.

    Args:
        message: Description of the conflict.
    """

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            status_code=HTTPStatus.CONFLICT,
            error_code="CONFLICT",
        )


class UnauthorizedError(AppException):
    """Raised when a request lacks valid authentication credentials.

    Args:
        message: Optional custom message (defaults to a standard description).
    """

    def __init__(self, message: str = "Authentication credentials are missing or invalid.") -> None:
        super().__init__(
            message=message,
            status_code=HTTPStatus.UNAUTHORIZED,
            error_code="UNAUTHORIZED",
        )


class ForbiddenError(AppException):
    """Raised when authenticated user lacks permission for an action.

    Args:
        message: Optional custom message.
    """

    def __init__(self, message: str = "You do not have permission to perform this action.") -> None:
        super().__init__(
            message=message,
            status_code=HTTPStatus.FORBIDDEN,
            error_code="FORBIDDEN",
        )


class ServiceUnavailableError(AppException):
    """Raised when a downstream service or dependency is unavailable.

    Args:
        service: Name of the unavailable service (e.g., "PostgreSQL").
    """

    def __init__(self, service: str) -> None:
        super().__init__(
            message=f"Downstream service '{service}' is currently unavailable.",
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            error_code="SERVICE_UNAVAILABLE",
        )


class ExternalServiceError(AppException):
    """Raised when an external API returns an unexpected error.

    Args:
        service: External service name.
        message: Contextual error message.
    """

    def __init__(self, service: str, message: str) -> None:
        super().__init__(
            message=f"Error communicating with '{service}': {message}",
            status_code=HTTPStatus.BAD_GATEWAY,
            error_code="EXTERNAL_SERVICE_ERROR",
        )


# ── Repository-specific exceptions ────────────────────────────────────────────


class RepositoryNotFoundError(NotFoundError):
    """Raised when a repository lookup by ID or URL returns no result.

    Args:
        identifier: The UUID string or URL that was not found.
    """

    def __init__(self, identifier: str) -> None:
        super().__init__(resource="Repository", identifier=identifier)


class RepositoryAlreadyExistsError(ConflictError):
    """Raised when attempting to register a URL that is already tracked.

    Args:
        github_url: The duplicate URL.
    """

    def __init__(self, github_url: str) -> None:
        super().__init__(
            message=(
                f"Repository '{github_url}' is already registered. "
                "Pass reclone=true to force a fresh clone."
            )
        )


class RepositoryCloneError(AppException):
    """Raised when a git clone operation fails.

    Args:
        github_url: The URL that failed to clone.
        reason: Low-level error description.
    """

    def __init__(self, github_url: str, reason: str) -> None:
        super().__init__(
            message=f"Failed to clone repository '{github_url}': {reason}",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            error_code="CLONE_FAILED",
        )


class RepositoryAccessError(AppException):
    """Raised when a repository is private or otherwise inaccessible.

    Args:
        github_url: The URL that could not be accessed.
    """

    def __init__(self, github_url: str) -> None:
        super().__init__(
            message=(
                f"Repository '{github_url}' is not accessible. "
                "It may be private or require a GitHub token."
            ),
            status_code=HTTPStatus.FORBIDDEN,
            error_code="REPOSITORY_ACCESS_DENIED",
        )


class RepositoryEmptyError(AppException):
    """Raised when a repository has no commits (empty repository).

    Args:
        github_url: The URL of the empty repository.
    """

    def __init__(self, github_url: str) -> None:
        super().__init__(
            message=f"Repository '{github_url}' is empty and cannot be cloned.",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            error_code="REPOSITORY_EMPTY",
        )


# ── Scanner-specific exceptions ────────────────────────────────────────────────


class ScannerError(AppException):
    """Base class for scanner-specific errors.

    Args:
        message: Human-readable description of the scan failure.
    """

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code="SCANNER_ERROR",
        )


class RepositoryNotReadyError(AppException):
    """Raised when a scan is requested for a repository that is not yet cloned.

    Args:
        repository_id: UUID string of the repository that is not ready.
        current_status: The current clone_status value.
    """

    def __init__(self, repository_id: str, current_status: str) -> None:
        super().__init__(
            message=(
                f"Repository '{repository_id}' cannot be scanned because its "
                f"clone status is '{current_status}'. "
                "Wait until the clone completes (status=READY)."
            ),
            status_code=HTTPStatus.CONFLICT,
            error_code="REPOSITORY_NOT_READY",
        )


class ScanAlreadyRunningError(AppException):
    """Raised when a scan is requested for a repository that is already scanning.

    Args:
        repository_id: UUID string of the repository already being scanned.
    """

    def __init__(self, repository_id: str) -> None:
        super().__init__(
            message=(
                f"Repository '{repository_id}' is already being scanned. "
                "Wait for the current scan to complete."
            ),
            status_code=HTTPStatus.CONFLICT,
            error_code="SCAN_ALREADY_RUNNING",
        )
