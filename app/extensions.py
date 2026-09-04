"""Расширения Flask без привязки к конкретному приложению."""

import sqlite3

from authlib.integrations.flask_client import OAuth
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Базовый класс типизированных SQLAlchemy-моделей."""


db = SQLAlchemy(model_class=Base)
oauth = OAuth()


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(connection: object, _record: object) -> None:
    """Включить проверку внешних ключей для каждого SQLite-соединения."""

    if isinstance(connection, sqlite3.Connection):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
