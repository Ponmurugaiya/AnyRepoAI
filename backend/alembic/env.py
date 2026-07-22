"""Alembic migration environment.

Configures Alembic to use the application's SQLAlchemy metadata and
sync database URL. Supports both online and offline migration modes.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure backend package is importable from this script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import declarative Base to capture all model metadata
from backend.app.db.base import Base  # noqa: E402
from backend.app.core.config import get_settings  # noqa: E402

# Import all model modules here so Alembic can detect table changes.
from backend.app.models import repository  # noqa: F401
from backend.app.models import file  # noqa: F401

# Alembic Config object providing access to alembic.ini values
config = context.config

# Configure stdlib logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override database URL with value from application settings
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database.sync_url)

# Use application model metadata for autogenerate support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Renders SQL to stdout without an active DB connection.
    Useful for generating migration scripts for review.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
