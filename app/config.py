"""Настройки приложения из переменных окружения."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """Базовая конфигурация Flask и OAuth Яндекса."""

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'time.sqlite3'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    YANDEX_CLIENT_ID = os.getenv("YANDEX_CLIENT_ID", "")
    YANDEX_CLIENT_SECRET = os.getenv("YANDEX_CLIENT_SECRET", "")

