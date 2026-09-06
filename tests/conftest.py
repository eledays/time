"""Общие фикстуры тестов приложения."""

from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User


class TestConfig(Config):
    """Изолированная конфигурация для тестов."""

    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    YANDEX_CLIENT_ID = ""
    YANDEX_CLIENT_SECRET = ""
    YANDEX_MAPS_API_KEY = "test-map-key"


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
        account = User(yandex_id="42", display_name="Лев", email="lev@example.ru")
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
