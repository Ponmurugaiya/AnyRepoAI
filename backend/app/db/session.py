"""SQLAlchemy async session management and connection pooling."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

# Global engine and session factory, initialized at startup
_engine = None
_async_session_factory = None


def init_db() -> None:
    """Initialize the async database engine and session factory.

    Should be called exactly once during application startup lifespan.
    """
    global _engine, _async_session_factory

    settings = get_settings()

    logger.info(
        "Initializing database connection",
        host=settings.database.host,
        port=settings.database.port,
        database=settings.database.db,
    )

    _engine = create_async_engine(
        settings.database.async_url,
        echo=settings.database.echo,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
        pool_timeout=settings.database.pool_timeout,
        pool_pre_ping=True,  # Verify connections before using
        # Use NullPool in testing to avoid connection leak issues
        poolclass=NullPool if settings.app.environment == "testing" else None,
    )

    _async_session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    logger.info("Database connection initialized successfully")


async def close_db() -> None:
    """Dispose of the database engine and close all connections.

    Should be called once during application shutdown lifespan.
    """
    global _engine

    if _engine:
        logger.info("Closing database connections")
        await _engine.dispose()
        logger.info("Database connections closed")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields a database session.

    Usage::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_session)):
            result = await db.execute(select(Item))
            return result.scalars().all()

    Yields:
        AsyncSession: A database session that auto-commits on success,
                      auto-rolls back on exceptions.
    """
    if _async_session_factory is None:
        raise RuntimeError(
            "Database not initialized. Call init_db() during application startup."
        )

    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_session_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database sessions outside of FastAPI dependencies.

    Usage::

        async with get_session_context() as db:
            result = await db.execute(select(Item))
            items = result.scalars().all()

    Yields:
        AsyncSession: A database session.
    """
    if _async_session_factory is None:
        raise RuntimeError(
            "Database not initialized. Call init_db() during application startup."
        )

    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
