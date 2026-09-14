"""Проверка пользовательской сессии."""

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from flask import current_app, g, redirect, request, session, url_for
from werkzeug.wrappers import Response

from app.extensions import db
from app.models import User

F = TypeVar("F", bound=Callable[..., Any])


def load_current_user() -> None:
    """Загрузить пользователя из сессии в контекст запроса."""

    user_id = session.get("user_id")
    g.user = db.session.get(User, user_id) if user_id else None


def require_current_terms() -> Response | None:
    """Не продолжать работу до принятия опубликованной версии условий."""

    if (
        g.user is None
        or g.user.terms_version == current_app.config["LEGAL_DOCUMENT_VERSION"]
    ):
        return None
    allowed_endpoints = {
        "auth.delete_account",
        "auth.logout",
        "health",
        "main.accept_legal_update",
        "main.legal_update",
        "main.privacy",
        "main.terms",
        "readiness",
        "static",
    }
    if request.endpoint in allowed_endpoints:
        return None
    return redirect(url_for("main.legal_update"))


def login_required(view: F) -> F:
    """Ограничить маршрут авторизованными пользователями."""

    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if g.user is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return cast(F, wrapped)
