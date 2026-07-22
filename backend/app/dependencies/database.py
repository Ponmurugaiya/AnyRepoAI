"""Database session dependency provider.

Wraps the SQLAlchemy session factory into a FastAPI dependency callable.
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for use in route handlers.

    The session commits on success and rolls back on any exception.

    Yields:
        AsyncSession: A live SQLAlchemy async session.

    Example::

        @router.get("/items/{item_id}")
        async def get_item(item_id: str, db: AsyncSession = Depends(get_db)):
            ...
    """
    async for session in get_session():
        yield session


# Annotated shorthand for cleaner route signatures
DBSession = Annotated[AsyncSession, Depends(get_db)]
