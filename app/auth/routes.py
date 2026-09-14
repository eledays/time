"""Вход, выход и удаление аккаунта через OAuth Яндекс ID."""

from datetime import datetime

from authlib.integrations.base_client.errors import OAuthError
from flask import current_app, flash, g, redirect, request, session, url_for
from requests import RequestException
from sqlalchemy import delete

from app.auth import bp
from app.auth.helpers import login_required
from app.extensions import db, limiter, oauth
from app.models import ActiveTrip, Place, Trip, User, utc_now


def yandex_avatar_url(profile: dict[str, object]) -> str:
    """Собрать URL портрета Яндекса или его штатной заглушки."""

    avatar_id = profile.get("default_avatar_id") or "0"
    return f"https://avatars.yandex.net/get-yapic/{avatar_id}/islands-200"


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("20 per minute")
def login():
    """Начать вход через Яндекс."""

    if request.method == "GET":
        return redirect(url_for("main.index"))
    if not current_app.config["YANDEX_CLIENT_ID"]:
        flash("Добавьте ключи Яндекс OAuth в .env", "warning")
        return redirect(url_for("main.index"))
    session["pending_terms_version"] = current_app.config["LEGAL_DOCUMENT_VERSION"]
    session["pending_terms_accepted_at"] = utc_now().isoformat()
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

    terms_version = session.get("pending_terms_version")
    accepted_at_value = session.get("pending_terms_accepted_at")
    if not terms_version or not accepted_at_value:
        flash("Начните вход с главной страницы", "warning")
        return redirect(url_for("main.index"))
    try:
        terms_accepted_at = datetime.fromisoformat(str(accepted_at_value))
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
            display_name=profile.get("display_name")
            or profile.get("login")
            or "Пользователь",
            email=profile.get("default_email"),
            avatar_url=avatar_url,
            terms_version=str(terms_version),
            terms_accepted_at=terms_accepted_at,
        )
        db.session.add(user)
    else:
        user.display_name = profile.get("display_name") or user.display_name
        user.email = profile.get("default_email") or user.email
        user.avatar_url = avatar_url or user.avatar_url
        user.terms_version = str(terms_version)
        user.terms_accepted_at = terms_accepted_at
    db.session.commit()
    session.clear()
    session.permanent = True
    session["user_id"] = user.id
    return redirect(url_for("main.index"))


@bp.post("/logout")
def logout():
    """Завершить локальную пользовательскую сессию."""

    session.clear()
    return redirect(url_for("main.index"))


@bp.post("/account/delete")
@limiter.limit("3 per hour")
@login_required
def delete_account():
    """Удалить профиль и все созданные им данные без возможности восстановления."""

    if request.form.get("confirmation", "").strip() != "УДАЛИТЬ":
        flash("Введите УДАЛИТЬ для подтверждения", "error")
        return redirect(url_for("main.profile", _anchor="delete-account"))

    user_id = g.user.id
    for model in (Trip, ActiveTrip, Place):
        db.session.execute(
            delete(model)
            .where(model.user_id == user_id)
            .execution_options(synchronize_session=False)
        )
    db.session.execute(
        delete(User)
        .where(User.id == user_id)
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    session.clear()
    flash("Аккаунт и все связанные данные удалены", "success")
    return redirect(url_for("main.index"))
