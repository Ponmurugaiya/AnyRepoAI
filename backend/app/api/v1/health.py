"""Health and liveness endpoints.

Provides:
  GET /api/v1/health  — Deep dependency health check.
  GET /api/v1/version — Application version and build metadata.
"""

import asyncio
import time
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.health import check_postgres_health
from backend.app.infrastructure.neo4j_client import check_neo4j_health
from backend.app.infrastructure.qdrant_client import check_qdrant_health
from backend.app.infrastructure.redis_client import check_redis_health
from backend.app.schemas.base import APIResponse

logger = get_logger(__name__)
router = APIRouter(tags=["Observability"])

# Track application start time for uptime reporting
_startup_time: float = time.monotonic()
_startup_dt: datetime = datetime.now(UTC)


@router.get(
    "/health",
    summary="Deep health check",
    description=(
        "Probes all downstream dependencies (PostgreSQL, Redis, Neo4j, Qdrant) "
        "and returns their individual status. Returns HTTP 200 when all services "
        "are healthy, HTTP 503 when one or more are unavailable."
    ),
    response_model=APIResponse,
)
async def health_check() -> JSONResponse:
    """Return aggregated health status for all platform dependencies.

    Returns:
        JSONResponse: 200 if all healthy, 503 if any dependency is down.
    """
    settings = get_settings()

    # Run all dependency probes concurrently
    postgres_status, redis_status, neo4j_status, qdrant_status = await asyncio.gather(
        check_postgres_health(),
        check_redis_health(),
        check_neo4j_health(),
        check_qdrant_health(),
    )

    uptime_seconds = round(time.monotonic() - _startup_time, 2)
    all_healthy = all(
        dep["status"] == "healthy"
        for dep in [postgres_status, redis_status, neo4j_status, qdrant_status]
    )

    health_data = {
        "status": "healthy" if all_healthy else "degraded",
        "version": settings.app.version,
        "environment": settings.app.environment,
        "uptime_seconds": uptime_seconds,
        "checked_at": datetime.now(UTC).isoformat(),
        "dependencies": {
            "postgres": postgres_status,
            "redis": redis_status,
            "neo4j": neo4j_status,
            "qdrant": qdrant_status,
        },
    }

    response = APIResponse.ok(
        data=health_data,
        message="All systems operational" if all_healthy else "One or more dependencies degraded",
    )

    http_status = 200 if all_healthy else 503
    return JSONResponse(content=response.model_dump(), status_code=http_status)


@router.get(
    "/version",
    summary="Application version",
    description="Returns the application name, version, and environment.",
    response_model=APIResponse,
)
async def get_version() -> APIResponse:
    """Return application version metadata.

    Returns:
        APIResponse: Version, name, and environment information.
    """
    settings = get_settings()

    version_data = {
        "name": settings.app.name,
        "version": settings.app.version,
        "environment": settings.app.environment,
        "started_at": _startup_dt.isoformat(),
    }

    return APIResponse.ok(data=version_data, message="Version retrieved successfully")
