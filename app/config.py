"""Строго валидируемые настройки приложения из окружения."""

import re
import secrets
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

BASE_DIR = Path(__file__).resolve().parent.parent
INSECURE_SECRET_KEYS = {
    "dev-change-me",
    "replace-with-a-random-string-at-least-32-characters",
}
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class Config(BaseSettings):
    """Проверить настройки до запуска Flask и подготовить его конфигурацию."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    environment: Literal["development", "testing", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    secret_key: SecretStr = Field(
        default_factory=lambda: SecretStr(secrets.token_urlsafe(32)),
        validation_alias="SECRET_KEY",
    )
    database_url: str = Field(
        default=f"sqlite:///{BASE_DIR / 'instance' / 'time.sqlite3'}",
        validation_alias="DATABASE_URL",
        repr=False,
    )
    instance_path: Path = Field(
        default=BASE_DIR / "instance", validation_alias="INSTANCE_PATH"
    )
    yandex_client_id: str = Field(default="", validation_alias="YANDEX_CLIENT_ID")
    yandex_client_secret: SecretStr = Field(
        default=SecretStr(""), validation_alias="YANDEX_CLIENT_SECRET"
    )
    public_url: AnyHttpUrl | None = Field(default=None, validation_alias="PUBLIC_URL")
    trusted_hosts: str = Field(default="", validation_alias="TRUSTED_HOSTS")
    session_cookie_secure: bool | None = Field(
        default=None, validation_alias="SESSION_COOKIE_SECURE"
    )
    max_content_length: int = Field(
        default=1_048_576,
        ge=16_384,
        le=10_485_760,
        validation_alias="MAX_CONTENT_LENGTH",
    )
    max_route_points: int = Field(
        default=20, ge=2, le=100, validation_alias="MAX_ROUTE_POINTS"
    )
    max_text_length: int = Field(
        default=200, ge=32, le=2_000, validation_alias="MAX_TEXT_LENGTH"
    )
    rate_limit_storage_uri: str = Field(
        default="memory://", validation_alias="RATE_LIMIT_STORAGE_URI"
    )
    trusted_proxy_count: int = Field(
        default=0, ge=0, le=10, validation_alias="TRUSTED_PROXY_COUNT"
    )
    session_lifetime_hours: int = Field(
        default=168, ge=1, le=8760, validation_alias="SESSION_LIFETIME_HOURS"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )
    legal_operator_name: str = Field(
        default="", max_length=300, validation_alias="LEGAL_OPERATOR_NAME"
    )
    legal_operator_email: str = Field(
        default="", max_length=254, validation_alias="LEGAL_OPERATOR_EMAIL"
    )
    legal_operator_address: str = Field(
        default="", max_length=500, validation_alias="LEGAL_OPERATOR_ADDRESS"
    )
    legal_operator_id: str = Field(
        default="", max_length=100, validation_alias="LEGAL_OPERATOR_ID"
    )
    legal_data_storage_location: str = Field(
        default="", max_length=300, validation_alias="LEGAL_DATA_STORAGE_LOCATION"
    )
    legal_hosting_provider_name: str = Field(
        default="", max_length=300, validation_alias="LEGAL_HOSTING_PROVIDER_NAME"
    )
    legal_hosting_provider_location: str = Field(
        default="", max_length=300, validation_alias="LEGAL_HOSTING_PROVIDER_LOCATION"
    )
    legal_rkn_notice_date: date | None = Field(
        default=None, validation_alias="LEGAL_RKN_NOTICE_DATE"
    )
    legal_cross_border_transfer: bool | None = Field(
        default=None, validation_alias="LEGAL_CROSS_BORDER_TRANSFER"
    )
    legal_cross_border_notice_date: date | None = Field(
        default=None, validation_alias="LEGAL_CROSS_BORDER_NOTICE_DATE"
    )
    legal_cross_border_countries: str = Field(
        default="", max_length=500, validation_alias="LEGAL_CROSS_BORDER_COUNTRIES"
    )
    legal_document_version: str = Field(
        default="1.1",
        min_length=1,
        max_length=30,
        validation_alias="LEGAL_DOCUMENT_VERSION",
    )
    legal_effective_date: date | None = Field(
        default=None, validation_alias="LEGAL_EFFECTIVE_DATE"
    )
    legal_backup_retention_days: int = Field(
        default=30,
        ge=0,
        le=365,
        validation_alias="LEGAL_BACKUP_RETENTION_DAYS",
    )
    legal_log_retention_days: int = Field(
        default=30,
        ge=1,
        le=365,
        validation_alias="LEGAL_LOG_RETENTION_DAYS",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        """Принимать только URL, понятный SQLAlchemy."""

        try:
            make_url(value)
        except ArgumentError as error:
            raise ValueError(
                "DATABASE_URL должен быть корректным URL SQLAlchemy"
            ) from error
        return value

    @field_validator("instance_path")
    @classmethod
    def normalize_instance_path(cls, value: Path) -> Path:
        """Передать Flask абсолютный путь, сохранив удобный локальный default."""

        return value if value.is_absolute() else BASE_DIR / value

    @field_validator("trusted_hosts")
    @classmethod
    def normalize_trusted_hosts(cls, value: str) -> str:
        """Убрать пустые элементы из списка разрешённых Host-заголовков."""

        hosts = [host.strip() for host in value.split(",") if host.strip()]
        if any(
            not re.fullmatch(r"(?:\*\.)?[A-Za-z0-9.-]+(?::\d+)?", host)
            for host in hosts
        ):
            raise ValueError("TRUSTED_HOSTS содержит некорректное имя хоста")
        return ",".join(hosts)

    @field_validator("rate_limit_storage_uri")
    @classmethod
    def validate_rate_limit_storage_uri(cls, value: str) -> str:
        """Не передавать Flask-Limiter пустой или заведомо неверный URI."""

        value = value.strip()
        if "://" not in value or any(character.isspace() for character in value):
            raise ValueError("RATE_LIMIT_STORAGE_URI должен быть корректным URI")
        return value

    @field_validator(
        "legal_operator_name",
        "legal_operator_email",
        "legal_operator_address",
        "legal_operator_id",
        "legal_data_storage_location",
        "legal_hosting_provider_name",
        "legal_hosting_provider_location",
        "legal_cross_border_countries",
        "legal_document_version",
    )
    @classmethod
    def normalize_legal_text(cls, value: str) -> str:
        """Убрать случайные пробелы из реквизитов юридических документов."""

        return " ".join(value.split())

    @field_validator("legal_operator_email")
    @classmethod
    def validate_legal_email(cls, value: str) -> str:
        """Проверить контактный email оператора, если он задан."""

        if value and not EMAIL_PATTERN.fullmatch(value):
            raise ValueError("LEGAL_OPERATOR_EMAIL должен быть корректным email")
        return value

    @model_validator(mode="after")
    def validate_security(self) -> "Config":
        """Запретить запуск production с небезопасными или неполными секретами."""

        secret = self.secret_key.get_secret_value()
        oauth_secret = self.yandex_client_secret.get_secret_value()
        if bool(self.yandex_client_id) != bool(oauth_secret):
            raise ValueError("YANDEX_CLIENT_ID и YANDEX_CLIENT_SECRET задаются вместе")
        if self.environment == "production":
            if "secret_key" not in self.model_fields_set:
                raise ValueError("production требует явно заданный SECRET_KEY")
            if secret in INSECURE_SECRET_KEYS or len(secret) < 32:
                raise ValueError(
                    "production SECRET_KEY должен содержать минимум 32 символа"
                )
            if not self.yandex_client_id:
                raise ValueError("production требует настройки Яндекс OAuth")
            if self.public_url is None:
                raise ValueError("production требует PUBLIC_URL")
            if self.public_url.scheme != "https":
                raise ValueError("production PUBLIC_URL должен использовать HTTPS")
            if self.session_cookie_secure is False:
                raise ValueError("production запрещает отключать SESSION_COOKIE_SECURE")
            if not self.trusted_hosts:
                raise ValueError("production требует TRUSTED_HOSTS")
            if self.trusted_proxy_count < 1:
                raise ValueError("production требует TRUSTED_PROXY_COUNT не меньше 1")
            database_url = make_url(self.database_url)
            if (
                database_url.get_backend_name() == "sqlite"
                and database_url.database != ":memory:"
                and not Path(database_url.database or "").is_absolute()
            ):
                raise ValueError(
                    "production SQLite DATABASE_URL должен содержать абсолютный путь"
                )
            public_host = self.public_url.host
            allowed_hosts = self.trusted_hosts.split(",")
            if public_host not in allowed_hosts and not any(
                host.startswith("*.") and public_host.endswith(host[1:])
                for host in allowed_hosts
            ):
                raise ValueError(
                    "хост PUBLIC_URL должен присутствовать в TRUSTED_HOSTS"
                )
            required_legal_fields = {
                "LEGAL_OPERATOR_NAME": self.legal_operator_name,
                "LEGAL_OPERATOR_EMAIL": self.legal_operator_email,
                "LEGAL_OPERATOR_ADDRESS": self.legal_operator_address,
                "LEGAL_DATA_STORAGE_LOCATION": self.legal_data_storage_location,
                "LEGAL_HOSTING_PROVIDER_NAME": self.legal_hosting_provider_name,
                "LEGAL_HOSTING_PROVIDER_LOCATION": self.legal_hosting_provider_location,
            }
            missing = [
                name for name, value in required_legal_fields.items() if not value
            ]
            if self.legal_effective_date is None:
                missing.append("LEGAL_EFFECTIVE_DATE")
            if missing:
                raise ValueError(
                    "production требует юридические реквизиты: " + ", ".join(missing)
                )
        return self

    def flask_mapping(self) -> dict[str, object]:
        """Вернуть только настройки, которые должен получить Flask."""

        secure_cookie = (
            self.environment == "production"
            if self.session_cookie_secure is None
            else self.session_cookie_secure
        )
        return {
            "ENVIRONMENT": self.environment,
            "INSTANCE_PATH": str(self.instance_path),
            "DEBUG": self.environment == "development",
            "TESTING": self.environment == "testing",
            "SECRET_KEY": self.secret_key.get_secret_value(),
            "SQLALCHEMY_DATABASE_URI": self.database_url,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "SESSION_COOKIE_SECURE": secure_cookie,
            "SESSION_COOKIE_NAME": "__Host-time_session"
            if secure_cookie
            else "session",
            "PERMANENT_SESSION_LIFETIME": timedelta(hours=self.session_lifetime_hours),
            "SESSION_REFRESH_EACH_REQUEST": False,
            "MAX_CONTENT_LENGTH": self.max_content_length,
            "MAX_ROUTE_POINTS": self.max_route_points,
            "MAX_TEXT_LENGTH": self.max_text_length,
            "YANDEX_CLIENT_ID": self.yandex_client_id,
            "YANDEX_CLIENT_SECRET": self.yandex_client_secret.get_secret_value(),
            "PUBLIC_URL": str(self.public_url).rstrip("/") if self.public_url else None,
            "TRUSTED_HOSTS": self.trusted_hosts.split(",")
            if self.trusted_hosts
            else None,
            "RATELIMIT_STORAGE_URI": self.rate_limit_storage_uri,
            "RATELIMIT_ENABLED": self.environment != "testing",
            "RATELIMIT_HEADERS_ENABLED": True,
            "TRUSTED_PROXY_COUNT": self.trusted_proxy_count,
            "LOG_LEVEL": self.log_level,
            "LEGAL_OPERATOR_NAME": self.legal_operator_name,
            "LEGAL_OPERATOR_EMAIL": self.legal_operator_email,
            "LEGAL_OPERATOR_ADDRESS": self.legal_operator_address,
            "LEGAL_OPERATOR_ID": self.legal_operator_id,
            "LEGAL_DATA_STORAGE_LOCATION": self.legal_data_storage_location,
            "LEGAL_HOSTING_PROVIDER_NAME": self.legal_hosting_provider_name,
            "LEGAL_HOSTING_PROVIDER_LOCATION": self.legal_hosting_provider_location,
            "LEGAL_RKN_NOTICE_DATE": self.legal_rkn_notice_date,
            "LEGAL_CROSS_BORDER_TRANSFER": self.legal_cross_border_transfer,
            "LEGAL_CROSS_BORDER_NOTICE_DATE": self.legal_cross_border_notice_date,
            "LEGAL_CROSS_BORDER_COUNTRIES": self.legal_cross_border_countries,
            "LEGAL_DOCUMENT_VERSION": self.legal_document_version,
            "LEGAL_EFFECTIVE_DATE": self.legal_effective_date,
            "LEGAL_BACKUP_RETENTION_DAYS": self.legal_backup_retention_days,
            "LEGAL_LOG_RETENTION_DAYS": self.legal_log_retention_days,
        }
