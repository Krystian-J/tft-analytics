from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Import your SQLAlchemy models here so Alembic can detect schema changes
# from crawler.db.models import Base  # uncomment once models are defined

# Import shared config to get database URL from .env
from shared.config import settings

# Alembic Config object — provides access to alembic.ini values
config = context.config

# Override sqlalchemy.url with value from .env via shared config
# This means the URL never needs to be hardcoded in alembic.ini
config.set_main_option("sqlalchemy.url", settings.POSTGRES_URL)

# Set up Python logging from alembic.ini config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate support
# Replace with Base.metadata once models are defined
target_metadata = None


def run_migrations_offline() -> None:
    """
    Run migrations in offline mode — generates SQL without a live DB connection.
    Useful for reviewing migrations before applying them.
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
    """
    Run migrations in online mode — applies migrations directly to the database.
    This is the mode used by: alembic upgrade head
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
