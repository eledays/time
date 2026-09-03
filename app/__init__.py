"""Фабрика Flask-приложения «Ход».

Модуль собирает конфигурацию, расширения и группы маршрутов в одном месте,
не создавая глобальное приложение при импорте пакета.
"""

from flask import Flask

from app.config import Config
from app.extensions import db, oauth


def create_app(config_object: type[Config] = Config) -> Flask:
    """Создать и настроить экземпляр Flask-приложения."""

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    db.init_app(app)
    oauth.init_app(app)

    from app.auth import bp as auth_bp
    from app.main import bp as main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    with app.app_context():
        db.create_all()

    return app

