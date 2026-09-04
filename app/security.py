"""Минимальная CSRF-защита для форм и JSON-запросов."""

import secrets

from flask import Flask, abort, request, session


def csrf_token() -> str:
    """Получить или создать CSRF-токен текущей сессии."""

    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return str(session["csrf_token"])


def init_csrf(app: Flask) -> None:
    """Подключить проверку токена ко всем изменяющим запросам."""

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def protect_post_requests() -> None:
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return
        provided = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        expected = session.get("csrf_token")
        if not expected or not provided or not secrets.compare_digest(expected, provided):
            abort(400, description="Некорректный CSRF-токен")

