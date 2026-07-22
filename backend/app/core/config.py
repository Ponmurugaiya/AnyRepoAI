"""Application configuration management.

Uses pydantic-settings to load configuration from environment variables
and .env files. All settings are typed and validated at startup.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection settings."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", extra="ignore")

    host: str = Field(default="localhost", description="PostgreSQL host")
    port: int = Field(default=5432, description="PostgreSQL port")
    user: str = Field(default="postgres", description="PostgreSQL user")
    password: str = Field(default="postgres", description="PostgreSQL password")
    db: str = Field(default="codebase_intel", description="PostgreSQL database name")
    pool_size: int = Field(default=10, description="SQLAlchemy connection pool size")
    max_overflow: int = Field(default=20, description="SQLAlchemy max overflow connections")
    pool_timeout: int = Field(default=30, description="Pool connection timeout in seconds")
    echo: bool = Field(default=False, description="Echo SQL queries (dev only)")

    @property
    def async_url(self) -> str:
        """Async SQLAlchemy connection URL using asyncpg driver."""
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db}"
        )

    @property
    def sync_url(self) -> str:
        """Sync SQLAlchemy connection URL for Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db}"
        )


class RedisSettings(BaseSettings):
    """Redis connection settings."""

    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="ignore")

    host: str = Field(default="localhost", description="Redis host")
    port: int = Field(default=6379, description="Redis port")
    password: str | None = Field(default=None, description="Redis password (optional)")
    db: int = Field(default=0, description="Redis database index")
    max_connections: int = Field(default=50, description="Max connections in pool")
    socket_timeout: float = Field(default=5.0, description="Socket timeout in seconds")
    socket_connect_timeout: float = Field(default=5.0, description="Connect timeout in seconds")

    @property
    def url(self) -> str:
        """Redis connection URL."""
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class QdrantSettings(BaseSettings):
    """Qdrant vector database connection settings."""

    model_config = SettingsConfigDict(env_prefix="QDRANT_", extra="ignore")

    host: str = Field(default="localhost", description="Qdrant host")
    port: int = Field(default=6333, description="Qdrant HTTP port")
    grpc_port: int = Field(default=6334, description="Qdrant gRPC port")
    api_key: str | None = Field(default=None, description="Qdrant API key (cloud)")
    prefer_grpc: bool = Field(default=False, description="Prefer gRPC transport")
    timeout: float = Field(default=10.0, description="Request timeout in seconds")


class Neo4jSettings(BaseSettings):
    """Neo4j graph database connection settings."""

    model_config = SettingsConfigDict(env_prefix="NEO4J_", extra="ignore")

    uri: str = Field(default="bolt://localhost:7687", description="Neo4j bolt URI")
    user: str = Field(default="neo4j", description="Neo4j username")
    password: str = Field(default="neo4j_password", description="Neo4j password")
    max_connection_pool_size: int = Field(default=50, description="Driver pool size")
    connection_timeout: float = Field(default=10.0, description="Connection timeout in seconds")


class RepositorySettings(BaseSettings):
    """Settings for the Repository Management module."""

    model_config = SettingsConfigDict(env_prefix="REPO_", extra="ignore")

    clone_root: str = Field(
        default="/storage/repos",
        description="Absolute filesystem path where repositories are cloned",
    )
    clone_timeout: int = Field(
        default=300,
        description="Maximum number of seconds to wait for a git clone to complete",
    )
    max_repo_size_mb: int = Field(
        default=2048,
        description="Maximum allowed repository size in MB (reserved for future enforcement)",
    )
    github_api_base_url: str = Field(
        default="https://api.github.com",
        description="Base URL for the GitHub REST API",
    )
    github_token: str | None = Field(
        default=None,
        description=(
            "Optional GitHub Personal Access Token. "
            "Required for private repositories and higher rate limits."
        ),
    )


class AppSettings(BaseSettings):
    """Core application settings."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        extra="ignore",
    )

    name: str = Field(default="Codebase Intelligence Platform", description="Application name")
    version: str = Field(default="0.1.0", description="Application version")
    environment: Literal["development", "staging", "production"] = Field(
        default="development", description="Deployment environment"
    )
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )
    # Store as a plain string to avoid pydantic-settings v2 attempting JSON-parse
    # on list fields from env vars. Use the cors_origins_list property in app code.
    cors_origins: str = Field(
        default="http://localhost:3000",
        description="Comma-separated CORS origins",
    )
    api_v1_prefix: str = Field(default="/api/v1", description="API v1 route prefix")
    request_timeout: float = Field(default=60.0, description="Global request timeout in seconds")

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS origins as a parsed list.

        Accepts either comma-separated or JSON-array format:
          - 'http://localhost:3000,http://localhost:3001'
          - '["http://localhost:3000","http://localhost:3001"]'
        """
        import json
        value = self.cors_origins.strip()
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except json.JSONDecodeError:
                pass
        return [origin.strip() for origin in value.split(",") if origin.strip()]


class Settings(BaseSettings):
    """Root settings aggregator.

    Composes all sub-settings. Load once via get_settings().
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    repository: RepositorySettings = Field(default_factory=RepositorySettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings singleton.

    Uses lru_cache so settings are only parsed once per process.
    Override in tests by calling get_settings.cache_clear().

    Returns:
        Settings: Fully validated application configuration.
    """
    return Settings()
