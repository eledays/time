"""Общие фикстуры тестов приложения."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Literal

import pytest
from flask import Flask
from flask.testing import FlaskClient
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User


class TestConfig(Config):
    """Изолированная конфигурация для тестов."""

    model_config = SettingsConfigDict(env_file=None, populate_by_name=True)
    environment: Literal["testing"] = "testing"
    secret_key: SecretStr = SecretStr("test-secret")
    database_url: str = "sqlite:///:memory:"
    yandex_client_id: str = ""
    yandex_client_secret: SecretStr = SecretStr("")


@pytest.fixture()
def app() -> Iterator[Flask]:
    """Создать приложение с чистой базой в памяти."""

    application = create_app(TestConfig)
    with application.app_context():
        db.drop_all()
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app: Flask) -> FlaskClient:
    """Вернуть тестовый HTTP-клиент."""

    return app.test_client()


@pytest.fixture()
def user(app: Flask) -> User:
    """Создать пользователя для авторизованных сценариев."""

    with app.app_context():
        account = User(
            yandex_id="42",
            display_name="Лев",
            terms_version="1.1",
            terms_accepted_at=datetime.now(UTC),
        )
        db.session.add(account)
        db.session.commit()
        db.session.refresh(account)
        db.session.expunge(account)
        return account


@pytest.fixture()
def auth_client(client: FlaskClient, user: User) -> FlaskClient:
    """Авторизовать тестовый клиент и выдать ему CSRF-токен."""

    with client.session_transaction() as session:
        session["user_id"] = user.id
        session["csrf_token"] = "test-csrf"
    return client
