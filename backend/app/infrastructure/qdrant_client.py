"""Qdrant vector database client factory and health probe.

Initialises a shared QdrantClient instance at startup and provides
a dependency for injection into service layer components.
"""

from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level client, initialized at startup
_qdrant_client: AsyncQdrantClient | None = None


def init_qdrant() -> None:
    """Initialize the Qdrant async client.

    Should be called once during application startup lifespan.
    """
    global _qdrant_client

    settings = get_settings()

    logger.info(
        "Initializing Qdrant connection",
        host=settings.qdrant.host,
        port=settings.qdrant.port,
    )

    _qdrant_client = AsyncQdrantClient(
        host=settings.qdrant.host,
        port=settings.qdrant.port,
        grpc_port=settings.qdrant.grpc_port,
        api_key=settings.qdrant.api_key,
        prefer_grpc=settings.qdrant.prefer_grpc,
        timeout=settings.qdrant.timeout,
    )

    logger.info("Qdrant connection initialized successfully")


async def close_qdrant() -> None:
    """Close the Qdrant client connection.

    Should be called once during application shutdown lifespan.
    """
    global _qdrant_client

    if _qdrant_client:
        logger.info("Closing Qdrant connection")
        await _qdrant_client.close()
        logger.info("Qdrant connection closed")


def get_qdrant() -> AsyncQdrantClient:
    """Return the shared Qdrant async client instance.

    Usage as a FastAPI dependency::

        @router.post("/vectors")
        async def store_vector(qdrant: AsyncQdrantClient = Depends(get_qdrant)):
            ...

    Returns:
        AsyncQdrantClient: The initialized Qdrant client.

    Raises:
        RuntimeError: If called before ``init_qdrant()`` at startup.
    """
    if _qdrant_client is None:
        raise RuntimeError(
            "Qdrant client not initialized. Call init_qdrant() during application startup."
        )
    return _qdrant_client


async def check_qdrant_health() -> dict[str, str]:
    """Probe Qdrant by fetching service health information.

    Returns:
        dict: Status dict with keys ``status`` and optionally ``error``.
              Possible status values: ``"healthy"``, ``"unhealthy"``.
    """
    try:
        client = get_qdrant()
        # list_collections is a lightweight operation that confirms connectivity
        await client.get_collections()
        return {"status": "healthy"}
    except UnexpectedResponse as exc:
        logger.warning("Qdrant health check failed (unexpected response)", error=str(exc))
        return {"status": "unhealthy", "error": "Unexpected response from Qdrant"}
    except ResponseHandlingException as exc:
        logger.warning("Qdrant health check failed (connection)", error=str(exc))
        return {"status": "unhealthy", "error": "Connection refused or timeout"}
    except RuntimeError as exc:
        return {"status": "unhealthy", "error": str(exc)}
    except Exception as exc:
        logger.error("Qdrant health check failed (unknown)", error=str(exc))
        return {"status": "unhealthy", "error": "Unknown error"}
