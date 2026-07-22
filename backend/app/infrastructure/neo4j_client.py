"""Neo4j graph database driver factory and health probe.

Manages a singleton AsyncGraphDatabase driver for the application lifetime.
"""

from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level driver, initialized at startup
_neo4j_driver: AsyncDriver | None = None


def init_neo4j() -> None:
    """Initialize the Neo4j async driver.

    Should be called once during application startup lifespan.
    The driver manages its own internal connection pool.
    """
    global _neo4j_driver

    settings = get_settings()

    logger.info(
        "Initializing Neo4j connection",
        uri=settings.neo4j.uri,
        user=settings.neo4j.user,
    )

    _neo4j_driver = AsyncGraphDatabase.driver(
        settings.neo4j.uri,
        auth=(settings.neo4j.user, settings.neo4j.password),
        max_connection_pool_size=settings.neo4j.max_connection_pool_size,
        connection_timeout=settings.neo4j.connection_timeout,
    )

    logger.info("Neo4j connection initialized successfully")


async def close_neo4j() -> None:
    """Close the Neo4j driver and all pooled connections.

    Should be called once during application shutdown lifespan.
    """
    global _neo4j_driver

    if _neo4j_driver:
        logger.info("Closing Neo4j connections")
        await _neo4j_driver.close()
        logger.info("Neo4j connections closed")


def get_neo4j() -> AsyncDriver:
    """Return the shared Neo4j async driver instance.

    Usage as a FastAPI dependency::

        @router.get("/graph")
        async def query_graph(neo4j: AsyncDriver = Depends(get_neo4j)):
            async with neo4j.session() as session:
                result = await session.run("MATCH (n) RETURN count(n)")
                ...

    Returns:
        AsyncDriver: The initialized Neo4j async driver.

    Raises:
        RuntimeError: If called before ``init_neo4j()`` at startup.
    """
    if _neo4j_driver is None:
        raise RuntimeError(
            "Neo4j driver not initialized. Call init_neo4j() during application startup."
        )
    return _neo4j_driver


async def check_neo4j_health() -> dict[str, str]:
    """Probe Neo4j by verifying driver connectivity.

    Returns:
        dict: Status dict with keys ``status`` and optionally ``error``.
              Possible status values: ``"healthy"``, ``"unhealthy"``.
    """
    try:
        driver = get_neo4j()
        await driver.verify_connectivity()
        return {"status": "healthy"}
    except ServiceUnavailable as exc:
        logger.warning("Neo4j health check failed (service unavailable)", error=str(exc))
        return {"status": "unhealthy", "error": "Neo4j service unavailable"}
    except AuthError as exc:
        logger.error("Neo4j health check failed (auth error)", error=str(exc))
        return {"status": "unhealthy", "error": "Authentication failed"}
    except RuntimeError as exc:
        return {"status": "unhealthy", "error": str(exc)}
    except Exception as exc:
        logger.error("Neo4j health check failed (unknown)", error=str(exc))
        return {"status": "unhealthy", "error": "Unknown error"}
