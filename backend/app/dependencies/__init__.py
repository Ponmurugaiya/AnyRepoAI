"""FastAPI dependency providers.

All reusable Depends() callables live here, keeping route handlers thin.
"""

from backend.app.dependencies.database import get_db
from backend.app.dependencies.infrastructure import get_neo4j_driver, get_qdrant_client, get_redis_client

__all__ = [
    "get_db",
    "get_redis_client",
    "get_qdrant_client",
    "get_neo4j_driver",
]
