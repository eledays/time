"""Маршруты авторизации."""

from flask import Blueprint

bp = Blueprint("auth", __name__, url_prefix="/auth")

from app.auth.helpers import load_current_user  # noqa: E402

bp.before_app_request(load_current_user)

from app.auth import routes  # noqa: E402, F401
