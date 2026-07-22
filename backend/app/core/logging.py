"""Structured JSON logging configuration.

Configures structlog with JSON output, request context binding,
and consistent field naming across all log records.
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger


def add_app_context(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Add static application-level context to every log record.

    Args:
        logger: The wrapped logger instance.
        method_name: The log method name (e.g., "info", "error").
        event_dict: The mutable log event dictionary.

    Returns:
        EventDict: The enriched event dictionary.
    """
    from backend.app.core.config import get_settings

    settings = get_settings()
    event_dict.setdefault("app", settings.app.name)
    event_dict.setdefault("environment", settings.app.environment)
    event_dict.setdefault("version", settings.app.version)
    return event_dict


def rename_event_key(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Rename structlog's 'event' key to 'message' for log aggregator compatibility.

    Args:
        logger: The wrapped logger instance.
        method_name: The log method name.
        event_dict: The mutable log event dictionary.

    Returns:
        EventDict: The event dictionary with 'message' instead of 'event'.
    """
    event_dict["message"] = event_dict.pop("event")
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog and stdlib logging for JSON structured output.

    Should be called once at application startup before any logging occurs.

    Args:
        log_level: The minimum log level string (e.g., "INFO", "DEBUG").
    """
    # Configure stdlib logging to route through structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        add_app_context,
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Remove default handlers before adding our own
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a named structlog logger.

    Args:
        name: Logger name, typically the module ``__name__``.

    Returns:
        structlog.stdlib.BoundLogger: A bound logger ready for use.
    """
    return structlog.get_logger(name)
