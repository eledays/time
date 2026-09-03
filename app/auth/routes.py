"""Заготовка маршрутов OAuth Яндекса."""

from flask import redirect, url_for

from app.auth import bp


@bp.get("/login")
def login():
    """Начать вход через Яндекс."""

    return redirect(url_for("main.index"))

