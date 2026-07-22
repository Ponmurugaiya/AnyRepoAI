"""Request ID middleware.

Assigns a unique ULID to every incoming request, attaches it as a
response header, and binds it to the structlog context so all log
records emitted during that request include the request_id field.
"""

import time
from collections.abc import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from ulid import ULID

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
PROCESS_TIME_HEADER = "X-Process-Time-Ms"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that injects a unique request ID into every request lifecycle.

    Behaviour:
        - Reads ``X-Request-ID`` from the incoming request if present,
          otherwise generates a new ULID.
        - Binds ``request_id`` to the structlog context so every log line
          emitted during the request automatically includes it.
        - Appends ``X-Request-ID`` and ``X-Process-Time-Ms`` to the response.
        - Logs a structured access record at INFO level after the response.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request, inject request ID, and log the access record.

        Args:
            request: The incoming HTTP request.
            call_next: ASGI callable to pass control to the next layer.

        Returns:
            Response: The HTTP response with injected tracing headers.
        """
        # Reuse upstream-provided ID (e.g., from load balancer) or generate one
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(ULID())

        # Bind request_id to structlog context for the lifetime of this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start_time = time.monotonic()

        response = await call_next(request)

        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        # Attach tracing headers to the outgoing response
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[PROCESS_TIME_HEADER] = str(duration_ms)

        # Structured access log consistent with the /health spec
        logger.info(
            "HTTP request processed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=duration_ms,
            client_host=request.client.host if request.client else "unknown",
        )

        return response
