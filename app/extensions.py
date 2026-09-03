"""Расширения Flask без привязки к конкретному приложению."""

from authlib.integrations.flask_client import OAuth
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Базовый класс типизированных SQLAlchemy-моделей."""


db = SQLAlchemy(model_class=Base)
oauth = OAuth()

