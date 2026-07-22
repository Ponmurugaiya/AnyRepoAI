"""Infrastructure clients: Redis, Qdrant, Neo4j, GitHub."""

from backend.app.infrastructure.github_client import (
    GitHubClient,
    close_github_client,
    get_github_client,
)
from backend.app.infrastructure.neo4j_client import (
    check_neo4j_health,
    close_neo4j,
    get_neo4j,
    init_neo4j,
)
from backend.app.infrastructure.qdrant_client import (
    check_qdrant_health,
    close_qdrant,
    get_qdrant,
    init_qdrant,
)
from backend.app.infrastructure.redis_client import (
    check_redis_health,
    close_redis,
    get_redis,
    init_redis,
)

__all__ = [
    # Redis
    "init_redis",
    "close_redis",
    "get_redis",
    "check_redis_health",
    # Qdrant
    "init_qdrant",
    "close_qdrant",
    "get_qdrant",
    "check_qdrant_health",
    # Neo4j
    "init_neo4j",
    "close_neo4j",
    "get_neo4j",
    "check_neo4j_health",
    # GitHub
    "GitHubClient",
    "get_github_client",
    "close_github_client",
]
