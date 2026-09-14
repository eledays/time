"""Alembic environment connected to the Flask application."""

from logging.config import fileConfig

from alembic import context
from flask import current_app

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def get_engine():
    """Return the SQLAlchemy engine configured by Flask-SQLAlchemy."""

    return current_app.extensions["migrate"].db.engine


def get_metadata():
    """Return model metadata used by Alembic autogeneration."""

    return current_app.extensions["migrate"].db.metadata


def run_migrations_offline() -> None:
    """Run migrations without creating a live connection."""

    url = str(get_engine().url).replace("%", "%%")
    context.configure(
        url=url,
        target_metadata=get_metadata(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **current_app.extensions["migrate"].configure_args,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in a transaction against the configured database."""

    with get_engine().connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            **current_app.extensions["migrate"].configure_args,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
