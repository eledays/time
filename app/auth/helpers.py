"""Проверка пользовательской сессии."""

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from flask import g, redirect, session, url_for

from app.extensions import db
from app.models import User

F = TypeVar("F", bound=Callable[..., Any])


def load_current_user() -> None:
    """Загрузить пользователя из сессии в контекст запроса."""

    user_id = session.get("user_id")
    g.user = db.session.get(User, user_id) if user_id else None


def login_required(view: F) -> F:
    """Ограничить маршрут авторизованными пользователями."""

    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if g.user is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return cast(F, wrapped)

