"""Фабрика Flask-приложения «Ход».

Модуль собирает конфигурацию, расширения и группы маршрутов в одном месте,
не создавая глобальное приложение при импорте пакета.
"""

from pathlib import Path

from flask import Flask, g, render_template, request
from sqlalchemy import text

from app.config import Config
from app.extensions import db, limiter, oauth
from app.security import init_csrf
from app.schema import upgrade_sqlite_schema


def create_app(config_object: Config | type[Config] = Config) -> Flask:
    """Создать и настроить экземпляр Flask-приложения."""

    settings = config_object() if isinstance(config_object, type) else config_object
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(settings.flask_mapping())
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
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
        client_kwargs={"scope": "login:email login:info login:avatar"},
    )

    from app.auth import bp as auth_bp
    from app.main import bp as main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    with app.app_context():
        db.create_all()
        if db.engine.dialect.name == "sqlite":
            upgrade_sqlite_schema()
            db.session.execute(text("PRAGMA optimize"))
        db.session.commit()

    @app.after_request
    def add_security_headers(response):
        """Добавить базовые браузерные защиты ко всем ответам."""

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://avatars.yandex.net https://server.arcgisonline.com; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if g.get("user") is not None and request.endpoint != "static":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.errorhandler(404)
    def not_found(_error: Exception) -> tuple[str, int]:
        """Показать аккуратную страницу для неизвестного адреса."""

        return render_template("error.html", code=404, message="Здесь ничего нет"), 404

    @app.errorhandler(413)
    def request_too_large(_error: Exception) -> tuple[str, int]:
        """Отклонить запрос, превышающий разрешённый размер."""

        return render_template("error.html", code=413, message="Запрос слишком большой"), 413

    @app.errorhandler(429)
    def too_many_requests(_error: Exception) -> tuple[str, int]:
        """Сообщить о временном превышении частоты запросов."""

        return render_template("error.html", code=429, message="Слишком много запросов"), 429

    @app.errorhandler(500)
    def server_error(_error: Exception) -> tuple[str, int]:
        """Показать нейтральное сообщение при внутренней ошибке."""

        return render_template("error.html", code=500, message="Что-то пошло не так"), 500

    return app
