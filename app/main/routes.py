"""Основные HTTP-маршруты приложения."""

from flask import render_template

from app.main import bp


@bp.get("/")
def index():
    """Показать форму записи поездки."""

    return render_template("index.html")

