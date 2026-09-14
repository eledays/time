"""Настройка структурированных эксплуатационных логов."""

from logging.config import dictConfig

from flask import Flask


def configure_logging(app: Flask) -> None:
    """Писать production-логи в stderr в удобном для сборщика формате."""

    if app.config["ENVIRONMENT"] != "production":
        return
    level = app.config["LOG_LEVEL"]
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "production": {
                    "format": (
                        "%(asctime)s level=%(levelname)s logger=%(name)s "
                        "message=%(message)s"
                    )
                }
            },
            "handlers": {
                "stderr": {
                    "class": "logging.StreamHandler",
                    "formatter": "production",
                    "stream": "ext://sys.stderr",
                }
            },
            "root": {"handlers": ["stderr"], "level": level},
            "loggers": {
                "gunicorn.error": {
                    "handlers": ["stderr"],
                    "level": level,
                    "propagate": False,
                },
                "gunicorn.access": {
                    "handlers": ["stderr"],
                    "level": "INFO",
                    "propagate": False,
                },
            },
        }
    )
