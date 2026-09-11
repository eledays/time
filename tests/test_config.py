"""Проверки строгой конфигурации приложения."""

import pytest
from pydantic import ValidationError

from app.config import Config

LEGAL_SETTINGS = {
    "legal_operator_name": "Иван Иванов",
    "legal_operator_email": "privacy@example.ru",
    "legal_operator_address": "Москва, Россия",
    "legal_data_storage_location": "Москва, Россия",
    "legal_effective_date": "2026-09-11",
}


def test_production_rejects_default_secret() -> None:
    """Production не запускается с известным резервным ключом."""

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Config(
            _env_file=None,
            environment="production",
            secret_key="dev-change-me",
            yandex_client_id="client",
            yandex_client_secret="secret",
            public_url="https://time.example",
            trusted_hosts="time.example",
        )

    with pytest.raises(ValidationError, match="явно заданный SECRET_KEY"):
        Config(
            _env_file=None,
            environment="production",
            yandex_client_id="client",
            yandex_client_secret="secret",
            public_url="https://time.example",
            trusted_hosts="time.example",
        )


def test_production_requires_https_and_matching_trusted_host() -> None:
    """Публичный OAuth-origin должен быть HTTPS и входить в trusted hosts."""

    common = {
        "_env_file": None,
        "environment": "production",
        "secret_key": "a" * 32,
        "yandex_client_id": "client",
        "yandex_client_secret": "secret",
        "trusted_hosts": "time.example",
    }
    with pytest.raises(ValidationError, match="HTTPS"):
        Config(**common, public_url="http://time.example")
    with pytest.raises(ValidationError, match="TRUSTED_HOSTS"):
        Config(**common, public_url="https://other.example")
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        Config(**common, public_url="https://time.example", session_cookie_secure=False)


def test_production_mapping_enables_secure_cookie() -> None:
    """Безопасные cookie включаются автоматически в production."""

    settings = Config(
        _env_file=None,
        environment="production",
        secret_key="a" * 32,
        yandex_client_id="client",
        yandex_client_secret="secret",
        public_url="https://time.example",
        trusted_hosts="time.example",
        **LEGAL_SETTINGS,
    )
    mapping = settings.flask_mapping()
    assert mapping["SESSION_COOKIE_SECURE"] is True
    assert mapping["SESSION_COOKIE_NAME"] == "__Host-time_session"
    assert mapping["TRUSTED_HOSTS"] == ["time.example"]
    assert mapping["LEGAL_OPERATOR_NAME"] == "Иван Иванов"


def test_production_requires_legal_operator_details() -> None:
    """Публичная версия не запускается с пустыми реквизитами документов."""

    with pytest.raises(ValidationError, match="юридические реквизиты"):
        Config(
            _env_file=None,
            environment="production",
            secret_key="a" * 32,
            yandex_client_id="client",
            yandex_client_secret="secret",
            public_url="https://time.example",
            trusted_hosts="time.example",
        )


def test_database_url_is_validated() -> None:
    """Некорректный URL базы отклоняется до инициализации Flask."""

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Config(_env_file=None, database_url="not a database url")


def test_development_secret_is_random_and_storage_uri_is_validated() -> None:
    """Локальный fallback безопасен, а URI лимитера проверяется заранее."""

    first = Config(_env_file=None)
    second = Config(_env_file=None)
    assert first.secret_key.get_secret_value() != second.secret_key.get_secret_value()
    assert len(first.secret_key.get_secret_value()) >= 32
    with pytest.raises(ValidationError, match="RATE_LIMIT_STORAGE_URI"):
        Config(_env_file=None, rate_limit_storage_uri="not a uri")


def test_environment_variable_aliases_are_supported() -> None:
    """Имена из .env напрямую преобразуются в типизированные поля."""

    settings = Config(
        _env_file=None,
        APP_ENV="testing",
        SECRET_KEY="test-secret",
        MAX_ROUTE_POINTS="12",
    )
    assert settings.environment == "testing"
    assert settings.max_route_points == 12
