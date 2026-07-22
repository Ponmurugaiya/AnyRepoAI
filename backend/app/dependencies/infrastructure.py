"""Infrastructure client dependency providers.

Provides FastAPI Depends() callables for Redis, Qdrant, and Neo4j clients.
"""

from typing import Annotated

from fastapi import Depends
from neo4j import AsyncDriver
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis

from backend.app.infrastructure.neo4j_client import get_neo4j
from backend.app.infrastructure.qdrant_client import get_qdrant
from backend.app.infrastructure.redis_client import get_redis


def get_redis_client() -> Redis:
    """Return the shared Redis client.

    Returns:
        Redis: Initialized async Redis client.

    Example::

        @router.get("/cache/{key}")
        async def read_cache(key: str, redis: Redis = Depends(get_redis_client)):
            value = await redis.get(key)
            ...
    """
    return get_redis()


def get_qdrant_client() -> AsyncQdrantClient:
    """Return the shared Qdrant async client.

    Returns:
        AsyncQdrantClient: Initialized Qdrant client.

    Example::

        @router.post("/vectors")
        async def upsert(qdrant: AsyncQdrantClient = Depends(get_qdrant_client)):
            ...
    """
    return get_qdrant()


def get_neo4j_driver() -> AsyncDriver:
    """Return the shared Neo4j async driver.

    Returns:
        AsyncDriver: Initialized Neo4j async driver.

    Example::

        @router.get("/graph")
        async def query(neo4j: AsyncDriver = Depends(get_neo4j_driver)):
            async with neo4j.session() as session:
                ...
    """
    return get_neo4j()


# Annotated shorthands for cleaner route signatures
RedisClient = Annotated[Redis, Depends(get_redis_client)]
QdrantClientDep = Annotated[AsyncQdrantClient, Depends(get_qdrant_client)]
Neo4jDriverDep = Annotated[AsyncDriver, Depends(get_neo4j_driver)]
