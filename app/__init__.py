"""Фабрика Flask-приложения для дневника поездок.

Модуль собирает конфигурацию, расширения и группы маршрутов в одном месте,
не создавая глобальное приложение при импорте пакета.
"""

import os
from pathlib import Path

from alembic.util.exc import CommandError
from flask import Flask, g, render_template, request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import Config
from app.extensions import db, limiter, migrate, oauth
from app.observability import configure_logging
from app.readiness import database_is_current
from app.security import init_csrf


def create_app(config_object: Config | type[Config] = Config) -> Flask:
    """Создать и настроить экземпляр Flask-приложения."""

    settings = config_object() if isinstance(config_object, type) else config_object
    if settings.environment == "production":
        os.umask(0o077)
    app = Flask(
        __name__,
        instance_relative_config=True,
        instance_path=str(settings.instance_path),
    )
    app.config.from_mapping(settings.flask_mapping())
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    configure_logging(app)

    proxy_count = app.config["TRUSTED_PROXY_COUNT"]
    if proxy_count:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=proxy_count,
            x_proto=proxy_count,
            x_host=proxy_count,
        )

    db.init_app(app)
    migrate.init_app(app, db, compare_type=True, render_as_batch=True)
    oauth.init_app(app)
    limiter.init_app(app)
    limiter.exempt(app.view_functions["static"])
    init_csrf(app)
    oauth.register(
        name="yandex",
        client_id=app.config["YANDEX_CLIENT_ID"],
        client_secret=app.config["YANDEX_CLIENT_SECRET"],
        authorize_url="https://oauth.yandex.ru/authorize",
        access_token_url="https://oauth.yandex.ru/token",
        client_kwargs={"scope": "login:info"},
    )

    from app.auth import bp as auth_bp
    from app.main import bp as main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @app.get("/healthz")
    @limiter.exempt
    def health() -> tuple[dict[str, str], int]:
        """Подтвердить, что процесс приложения отвечает."""

        return {"status": "ok"}, 200

    @app.get("/readyz")
    @limiter.exempt
    def readiness() -> tuple[dict[str, str], int]:
        """Подтвердить доступность базы данных для обработки запросов."""

        try:
            db.session.execute(text("SELECT 1"))
            if not database_is_current(db.engine):
                return {"status": "migrations_pending"}, 503
        except (CommandError, SQLAlchemyError, OSError):
            db.session.rollback()
            app.logger.warning("Проверка готовности базы данных завершилась ошибкой")
            return {"status": "unavailable"}, 503
        return {"status": "ok"}, 200

    @app.after_request
    def add_security_headers(response):
        """Добавить базовые браузерные защиты ко всем ответам."""

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://server.arcgisonline.com; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if (
            request.endpoint in {"health", "readiness"}
            or g.get("user") is not None
            and request.endpoint != "static"
        ):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.errorhandler(404)
    def not_found(_error: Exception) -> tuple[str, int]:
        """Показать аккуратную страницу для неизвестного адреса."""

        return render_template("error.html", code=404, message="Здесь ничего нет"), 404

    @app.errorhandler(413)
    def request_too_large(_error: Exception) -> tuple[str, int]:
        """Отклонить запрос, превышающий разрешённый размер."""

        return render_template(
            "error.html", code=413, message="Запрос слишком большой"
        ), 413

    @app.errorhandler(429)
    def too_many_requests(_error: Exception) -> tuple[str, int]:
        """Сообщить о временном превышении частоты запросов."""

        return render_template(
            "error.html", code=429, message="Слишком много запросов"
        ), 429

    @app.errorhandler(500)
    def server_error(_error: Exception) -> tuple[str, int]:
        """Показать нейтральное сообщение при внутренней ошибке."""

        return render_template(
            "error.html", code=500, message="Что-то пошло не так"
        ), 500

    return app
