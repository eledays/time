"""Фабрика Flask-приложения «Ход».

Модуль собирает конфигурацию, расширения и группы маршрутов в одном месте,
не создавая глобальное приложение при импорте пакета.
"""

from pathlib import Path

from flask import Flask, render_template

from app.config import Config
from app.extensions import db, oauth
from app.security import init_csrf


def create_app(config_object: type[Config] = Config) -> Flask:
    """Создать и настроить экземпляр Flask-приложения."""

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    oauth.init_app(app)
    init_csrf(app)
    oauth.register(
        name="yandex",
        client_id=app.config["YANDEX_CLIENT_ID"],
        client_secret=app.config["YANDEX_CLIENT_SECRET"],
        authorize_url="https://oauth.yandex.ru/authorize",
        access_token_url="https://oauth.yandex.ru/token",
        client_kwargs={"scope": "login:email login:info"},
    )

    from app.auth import bp as auth_bp
    from app.main import bp as main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    with app.app_context():
        db.create_all()

    @app.errorhandler(404)
    def not_found(_error: Exception) -> tuple[str, int]:
        """Показать аккуратную страницу для неизвестного адреса."""

        return render_template("error.html", code=404, message="Здесь ничего нет"), 404

    @app.errorhandler(500)
    def server_error(_error: Exception) -> tuple[str, int]:
        """Показать нейтральное сообщение при внутренней ошибке."""

        return render_template("error.html", code=500, message="Что-то пошло не так"), 500

    return app
