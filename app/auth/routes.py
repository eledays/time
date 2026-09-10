"""Вход и выход через OAuth Яндекс ID."""

from authlib.integrations.base_client.errors import OAuthError
from flask import current_app, flash, redirect, session, url_for
from requests import RequestException

from app.auth import bp
from app.extensions import db, limiter, oauth
from app.models import User


def yandex_avatar_url(profile: dict[str, object]) -> str:
    """Собрать URL портрета Яндекса или его штатной заглушки."""

    avatar_id = profile.get("default_avatar_id") or "0"
    return f"https://avatars.yandex.net/get-yapic/{avatar_id}/islands-200"


@bp.get("/login")
@limiter.limit("20 per minute")
def login():
    """Начать вход через Яндекс."""

    if not current_app.config["YANDEX_CLIENT_ID"]:
        flash("Добавьте ключи Яндекс OAuth в .env", "warning")
        return redirect(url_for("main.index"))
    public_url = current_app.config.get("PUBLIC_URL")
    redirect_uri = (
        f"{public_url}/auth/callback"
        if public_url
        else url_for("auth.callback", _external=True)
    )
    return oauth.yandex.authorize_redirect(redirect_uri)


@bp.get("/callback")
@limiter.limit("20 per minute")
def callback():
    """Обменять OAuth-код на токен и сохранить профиль в сессии."""

    try:
        token = oauth.yandex.authorize_access_token()
        response = oauth.yandex.get(
            "https://login.yandex.ru/info?format=json", token=token
        )
        response.raise_for_status()
        profile = response.json()
        yandex_id = str(profile["id"])
    except (OAuthError, RequestException, KeyError, TypeError, ValueError):
        current_app.logger.warning("Не удалось завершить OAuth-вход", exc_info=True)
        flash("Не удалось войти через Яндекс. Попробуйте ещё раз.", "error")
        return redirect(url_for("main.index"))
    user = db.session.scalar(db.select(User).where(User.yandex_id == yandex_id))
    avatar_url = yandex_avatar_url(profile)
    if user is None:
        user = User(
            yandex_id=yandex_id,
            display_name=profile.get("display_name") or profile.get("login") or "Пользователь",
            email=profile.get("default_email"),
            avatar_url=avatar_url,
        )
        db.session.add(user)
    else:
        user.display_name = profile.get("display_name") or user.display_name
        user.email = profile.get("default_email") or user.email
        user.avatar_url = avatar_url or user.avatar_url
    db.session.commit()
    session.clear()
    session["user_id"] = user.id
    return redirect(url_for("main.index"))


@bp.post("/logout")
def logout():
    """Завершить локальную пользовательскую сессию."""

    session.clear()
    return redirect(url_for("main.index"))
