from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# DAT-02: replaces app/db.py's init_db()/create_all as the production
# schema-management path. init_db() is left as-is for tests (a fresh
# SQLite file per test run genuinely doesn't need migration history —
# see that function's own docstring) but a real environment (dev, UAT,
# production) must be built and upgraded through these migrations only.
import app.models.attendance  # noqa: E402,F401
import app.models.canonical  # noqa: E402,F401
import app.models.connectors  # noqa: E402,F401
import app.models.identity  # noqa: E402,F401
import app.models.runs  # noqa: E402,F401
from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# For normal CLI use, alembic.ini's own sqlalchemy.url is just the
# generated placeholder — fall back to Tempo's own database_url
# (TEMPO_DATABASE_URL env var), the same setting app/db.py's engine uses,
# so there's one source of truth for "which database" in the common case.
# A caller that already set an explicit URL on this Config object before
# invoking a command (tests/test_migrations.py does exactly this, to run
# against a throwaway file) is trusted instead — overriding it here would
# silently redirect every migration test at app/config.py's default
# sqlite:///./tempo_dev.db regardless of what the caller asked for, which
# is exactly the bug this comment used to cause before it was caught by
# that test actually failing.
_ALEMBIC_INI_PLACEHOLDER_URL = "driver://user:pass@localhost/dbname"
if config.get_main_option("sqlalchemy.url") in (None, _ALEMBIC_INI_PLACEHOLDER_URL):
    config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
