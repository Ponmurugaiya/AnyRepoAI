"""Database health check probe."""

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from backend.app.core.logging import get_logger
from backend.app.db.session import get_session_context

logger = get_logger(__name__)


async def check_postgres_health() -> dict[str, str]:
    """Run a lightweight SQL probe against PostgreSQL.

    Returns:
        dict: Status dict with keys ``status`` and optionally ``error``.
    """
    try:
        async with get_session_context() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except OperationalError as exc:
        logger.warning("PostgreSQL health check failed (operational)", error=str(exc))
        return {"status": "unhealthy", "error": "Connection refused or timeout"}
    except SQLAlchemyError as exc:
        logger.error("PostgreSQL health check failed (unexpected)", error=str(exc))
        return {"status": "unhealthy", "error": "Unexpected database error"}
    except RuntimeError as exc:
        return {"status": "unhealthy", "error": str(exc)}
