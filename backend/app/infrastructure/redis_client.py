"""Redis client factory and connection management.

Provides a connection-pooled async Redis client backed by hiredis.
The client is initialised once at startup and reused across requests.
"""

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level client, initialized at startup
_redis_client: Redis | None = None


def init_redis() -> None:
    """Initialize the Redis connection pool and client.

    Should be called once during application startup lifespan.
    Uses a shared connection pool to maximise connection reuse.
    """
    global _redis_client

    settings = get_settings()

    logger.info(
        "Initializing Redis connection",
        host=settings.redis.host,
        port=settings.redis.port,
        db=settings.redis.db,
    )

    pool = aioredis.ConnectionPool.from_url(
        settings.redis.url,
        max_connections=settings.redis.max_connections,
        socket_timeout=settings.redis.socket_timeout,
        socket_connect_timeout=settings.redis.socket_connect_timeout,
        decode_responses=True,
        encoding="utf-8",
    )

    _redis_client = aioredis.Redis(connection_pool=pool)
    logger.info("Redis connection initialized successfully")


async def close_redis() -> None:
    """Close the Redis connection pool.

    Should be called once during application shutdown lifespan.
    """
    global _redis_client

    if _redis_client:
        logger.info("Closing Redis connections")
        await _redis_client.aclose()
        logger.info("Redis connections closed")


def get_redis() -> Redis:
    """Return the shared Redis client instance.

    Usage as a FastAPI dependency::

        @router.get("/cached")
        async def cached_endpoint(redis: Redis = Depends(get_redis)):
            value = await redis.get("my_key")

    Returns:
        Redis: The initialized async Redis client.

    Raises:
        RuntimeError: If called before ``init_redis()`` at startup.
    """
    if _redis_client is None:
        raise RuntimeError(
            "Redis client not initialized. Call init_redis() during application startup."
        )
    return _redis_client


async def check_redis_health() -> dict[str, str]:
    """Run a PING probe against Redis.

    Returns:
        dict: Status dict with keys ``status`` and optionally ``error``.
              Possible status values: ``"healthy"``, ``"unhealthy"``.
    """
    try:
        client = get_redis()
        pong = await client.ping()
        if pong:
            return {"status": "healthy"}
        return {"status": "unhealthy", "error": "PING returned unexpected response"}
    except RedisConnectionError as exc:
        logger.warning("Redis health check failed (connection)", error=str(exc))
        return {"status": "unhealthy", "error": "Connection refused"}
    except RedisTimeoutError as exc:
        logger.warning("Redis health check failed (timeout)", error=str(exc))
        return {"status": "unhealthy", "error": "Connection timed out"}
    except RuntimeError as exc:
        return {"status": "unhealthy", "error": str(exc)}
