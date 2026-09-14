"""Расширения Flask без привязки к конкретному приложению."""

import sqlite3

from authlib.integrations.flask_client import OAuth
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Базовый класс типизированных SQLAlchemy-моделей."""


db = SQLAlchemy(model_class=Base)
oauth = OAuth()
migrate = Migrate()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60 per minute", "240 per hour"],
)


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(connection: object, _record: object) -> None:
    """Включить проверку внешних ключей для каждого SQLite-соединения."""

    if isinstance(connection, sqlite3.Connection):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
