"""FastAPI application factory and lifecycle management.

Entry point for the API server. Initializes infrastructure clients,
configures middleware and exception handlers, and registers route modules.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.exception_handlers import (
    app_exception_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from backend.app.api.router import api_v1_router
from backend.app.core.config import get_settings
from backend.app.core.exceptions import AppException
from backend.app.core.logging import configure_logging, get_logger
from backend.app.db.session import close_db, init_db
from backend.app.infrastructure import (
    close_github_client,
    close_neo4j,
    close_qdrant,
    close_redis,
    init_neo4j,
    init_qdrant,
    init_redis,
)
from backend.app.middleware.request_id import RequestIDMiddleware

settings = get_settings()

# Configure structured JSON logging before anything else
configure_logging(log_level=settings.app.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle.

    Initializes all infrastructure clients at startup and disposes
    them gracefully at shutdown. Runs once per process.

    Args:
        app: The FastAPI application instance.

    Yields:
        None: Control is passed to the ASGI server for request handling.
    """
    logger.info(
        "Application startup initiated",
        name=settings.app.name,
        version=settings.app.version,
        environment=settings.app.environment,
    )

    # Initialize all infrastructure clients
    try:
        init_db()
        init_redis()
        init_qdrant()
        init_neo4j()
    except Exception as exc:
        logger.critical("Failed to initialize infrastructure", error=str(exc))
        raise

    logger.info("All infrastructure clients initialized successfully")
    logger.info("Application startup complete. Ready to accept requests.")

    # Yield control to the ASGI server
    yield

    # Shutdown: close all infrastructure clients
    logger.info("Application shutdown initiated")

    try:
        await close_db()
        await close_redis()
        await close_qdrant()
        await close_neo4j()
        await close_github_client()
    except Exception as exc:
        logger.error("Error during infrastructure shutdown", error=str(exc))

    logger.info("Application shutdown complete")


def create_application() -> FastAPI:
    """Factory function that creates and configures the FastAPI app.

    Returns:
        FastAPI: A fully configured application instance.
    """
    app = FastAPI(
        title=settings.app.name,
        version=settings.app.version,
        description="Production-grade AI Codebase Intelligence Platform (GitHub Codebase RAG)",
        docs_url="/api/docs" if settings.app.debug else None,
        redoc_url="/api/redoc" if settings.app.debug else None,
        openapi_url="/api/openapi.json" if settings.app.debug else None,
        lifespan=lifespan,
    )

    # Register CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register request ID middleware (must be after CORS to see CORS headers)
    app.add_middleware(RequestIDMiddleware)

    # Register global exception handlers
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # Register API routers
    app.include_router(api_v1_router, prefix=settings.app.api_v1_prefix)

    logger.info("FastAPI application configured successfully")
    return app


# Global app instance for ASGI servers (uvicorn, gunicorn, etc.)
app = create_application()
