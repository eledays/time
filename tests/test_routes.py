"""Интеграционные тесты страниц и API."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from flask import Flask
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict
from sqlalchemy import text

from app import create_app
from app.auth.routes import yandex_avatar_url
from app.config import Config
from app.extensions import db, oauth
from app.models import ActiveTrip, Place, Trip, User
from app.services import get_or_create_place


def test_home_is_available_without_login(client) -> None:
    """Главная показывает приглашение войти анонимному посетителю."""

    response = client.get("/")
    assert response.status_code == 200
    assert '<body class="login-page"' in response.text
    assert "Войти с Яндекс ID" in response.text
    assert 'src="/static/img/logo.png"' in response.text
    assert 'src="/static/img/yandex-id.svg"' in response.text
    assert "Пользовательское соглашение" in response.text
    assert "Политикой конфиденциальности" in response.text
    assert "data-theme-toggle" not in response.text
    assert '<meta name="theme-color" content="#090909">' in response.text
    assert 'rel="apple-touch-icon"' in response.text
    assert "/static/img/favicon/favicon-32x32.png" in response.text
    assert "/static/img/favicon/favicon-16x16.png" in response.text
    assert "/static/img/favicon/site.webmanifest" in response.text
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"


def test_calculator_requires_login(client) -> None:
    """Расчёт маршрута недоступен без сессии."""

    response = client.get("/calculate")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")


def test_yandex_login_is_started_by_confirmed_post(
    app: Flask, client, monkeypatch
) -> None:
    """Обычный GET не означает акцепт, а нажатие кнопки фиксирует его версию."""

    with app.app_context():
        yandex = oauth.create_client("yandex")
        monkeypatch.setattr(
            yandex,
            "authorize_redirect",
            lambda _redirect_uri: ("provider redirect", 302),
        )
    app.config["YANDEX_CLIENT_ID"] = "client"
    assert client.get("/auth/login").headers["Location"] == "/"
    with client.session_transaction() as session:
        session["csrf_token"] = "test-csrf"
    response = client.post("/auth/login", data={"csrf_token": "test-csrf"})
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["pending_terms_version"] == "1.0"
        assert session["pending_terms_accepted_at"]


def test_legal_documents_are_public(client) -> None:
    """Условия и политика доступны до входа в аккаунт."""

    terms = client.get("/terms")
    privacy = client.get("/privacy")
    assert terms.status_code == 200
    assert "Пользовательское соглашение" in terms.text
    assert (
        "Расчёты времени, расстояния и скорости являются ориентировочными" in terms.text
    )
    assert privacy.status_code == 200
    assert "Какие данные обрабатываются" in privacy.text
    assert "удалить самостоятельно" in privacy.text


def test_trip_survives_reopen_and_finishes_with_bus_number(
    app: Flask, auth_client, user
) -> None:
    """Старт хранится между запросами и превращается в завершённую поездку."""

    start_response = auth_client.post(
        "/trips/start",
        data={
            "csrf_token": "test-csrf",
            "origin": "  Дом  ",
            "departed_at": "2026-09-03T09:00",
        },
    )
    assert start_response.status_code == 302

    reopened_page = auth_client.get("/")
    assert reopened_page.status_code == 200
    assert "Куда приехали?" in reopened_page.text
    assert "Дом" in reopened_page.text
    assert 'class="transport-carousel"' in reopened_page.text
    assert 'type="radio" name="transport_type" value="walk"' in reopened_page.text
    assert 'value="walk" required' in reopened_page.text
    assert 'value="walk" checked' not in reopened_page.text
    assert 'value="train"' not in reopened_page.text
    assert "/static/img/transport/walk.png" in reopened_page.text
    assert "/static/img/transport/bus.png" in reopened_page.text
    assert "/static/img/transport/rail.png" in reopened_page.text
    assert "/static/img/transport/e-bike.png" in reopened_page.text
    assert "/static/img/transport/scooter.png" in reopened_page.text
    assert 'class="active-origin-card"' in reopened_page.text
    assert "data-elapsed" not in reopened_page.text
    assert 'class="destination-title"' in reopened_page.text

    finish_response = auth_client.post(
        "/trips/finish",
        data={
            "csrf_token": "test-csrf",
            "destination": "Парк",
            "arrived_at": "2026-09-03T09:36",
            "transport_type": "bus",
            "transport_detail": "39",
        },
    )
    assert finish_response.status_code == 302
    with app.app_context():
        trip = db.session.scalar(db.select(Trip))
        assert trip is not None
        assert trip.duration_minutes == 36
        assert trip.transport_detail == "39"
        assert trip.origin.name == "Дом"
        assert db.session.query(Place).count() == 2
        assert db.session.scalar(db.select(ActiveTrip)) is None


def test_trip_can_return_to_the_same_place(app: Flask, auth_client) -> None:
    """Поездка A → A сохраняется как полноценный замкнутый маршрут."""

    auth_client.post(
        "/trips/start",
        data={
            "csrf_token": "test-csrf",
            "origin": "Дом",
            "departed_at": "2026-09-03T09:00",
        },
    )
    response = auth_client.post(
        "/trips/finish",
        data={
            "csrf_token": "test-csrf",
            "destination": "Дом",
            "arrived_at": "2026-09-03T09:40",
            "transport_type": "walk",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        trip = db.session.scalar(db.select(Trip))
        assert trip is not None
        assert trip.origin_id == trip.destination_id
        assert trip.duration_minutes == 40
    calculation = auth_client.post(
        "/api/calculate",
        json={"points": ["Дом", "Дом"]},
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert calculation.status_code == 200
    assert calculation.json["complete"] is True
    assert calculation.json["total_minutes"] == 40


def test_departure_time_is_hidden_by_default(auth_client) -> None:
    """Ручной выбор времени отправления открывается отдельной кнопкой."""

    page = auth_client.get("/")
    assert 'id="departed_at" name="departed_at" type="hidden"' in page.text
    assert 'data-time-dialog-open="departed_at"' in page.text
    assert 'aria-label="Время отправления не сейчас"' in page.text
    assert 'data-time-dialog="departed_at"' in page.text
    assert "data-picker-date required disabled" in page.text
    assert 'data-picker-clock step="60" required disabled' in page.text
    assert 'class="material-symbols-rounded"' in page.text
    assert ">schedule</span>" in page.text
    for icon in ("add_circle", "route", "history", "location_on", "map", "person"):
        assert f">{icon}</span><small>" in page.text
    assert "fonts.googleapis.com/css2?family=Material+Symbols+Rounded" in page.text


def test_arrival_time_is_hidden_by_default(auth_client) -> None:
    """Ручной выбор времени прибытия открывается отдельной кнопкой."""

    auth_client.post(
        "/trips/start",
        data={
            "csrf_token": "test-csrf",
            "origin": "Дом",
            "departed_at": "2026-09-03T09:00",
        },
    )
    page = auth_client.get("/")
    assert 'id="arrived_at" name="arrived_at" type="hidden"' in page.text
    assert 'data-time-dialog-open="arrived_at"' in page.text
    assert 'aria-label="Время прибытия не сейчас"' in page.text
    assert 'data-time-dialog="arrived_at"' in page.text


def test_timezone_can_be_saved_from_profile(app: Flask, auth_client, user) -> None:
    """Пользователь может явно выбрать часовой пояс в профиле."""

    response = auth_client.post(
        "/profile/timezone",
        data={"csrf_token": "test-csrf", "timezone": "Asia/Yekaterinburg"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Часовой пояс сохранён" in response.text
    assert 'value="Asia/Yekaterinburg" selected' in response.text
    with app.app_context():
        assert db.session.get(User, user.id).timezone == "Asia/Yekaterinburg"


def test_invalid_timezone_is_rejected(app: Flask, auth_client, user) -> None:
    """Неизвестный идентификатор часового пояса не сохраняется."""

    response = auth_client.post(
        "/profile/timezone",
        data={"csrf_token": "test-csrf", "timezone": "Mars/Olympus"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Выберите корректный часовой пояс" in response.text
    with app.app_context():
        assert db.session.get(User, user.id).timezone is None


def test_timezone_is_detected_only_once(app: Flask, auth_client, user) -> None:
    """Автоопределение не перезаписывает уже сохранённый пояс."""

    headers = {"X-CSRF-Token": "test-csrf"}
    first = auth_client.post(
        "/api/timezone", json={"timezone": "Europe/Moscow"}, headers=headers
    )
    second = auth_client.post(
        "/api/timezone", json={"timezone": "Asia/Tokyo"}, headers=headers
    )
    assert first.status_code == 204
    assert second.status_code == 204
    with app.app_context():
        assert db.session.get(User, user.id).timezone == "Europe/Moscow"


def test_timezone_api_rejects_non_object_json(auth_client) -> None:
    """Неожиданный JSON не вызывает внутреннюю ошибку."""

    response = auth_client.post(
        "/api/timezone",
        json=["Europe/Moscow"],
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert response.status_code == 400


def test_transport_type_is_required(app: Flask, auth_client) -> None:
    """Поездка не сохраняется, пока пользователь не выбрал транспорт."""

    auth_client.post(
        "/trips/start",
        data={
            "csrf_token": "test-csrf",
            "origin": "Дом",
            "departed_at": "2026-09-03T09:00",
        },
    )
    response = auth_client.post(
        "/trips/finish",
        data={
            "csrf_token": "test-csrf",
            "destination": "Парк",
            "arrived_at": "2026-09-03T09:30",
        },
        follow_redirects=True,
    )
    assert "Выберите тип перемещения" in response.text
    with app.app_context():
        assert db.session.scalar(db.select(Trip)) is None
        assert db.session.scalar(db.select(ActiveTrip)) is not None


def test_other_transport_detail_is_saved(app: Flask, auth_client) -> None:
    """Для другого способа сохраняется введённое пользователем название."""

    auth_client.post(
        "/trips/start",
        data={
            "csrf_token": "test-csrf",
            "origin": "Дом",
            "departed_at": "2026-09-03T09:00",
        },
    )
    auth_client.post(
        "/trips/finish",
        data={
            "csrf_token": "test-csrf",
            "destination": "Парк",
            "arrived_at": "2026-09-03T09:30",
            "transport_type": "other",
            "transport_detail": "Ролики",
        },
    )
    with app.app_context():
        trip = db.session.scalar(db.select(Trip))
        assert trip is not None
        assert trip.transport_detail == "Ролики"


def test_rental_cost_defaults_to_zero(app: Flask, auth_client) -> None:
    """Бесплатная поездка на самокате сохраняет нулевую стоимость."""

    auth_client.post(
        "/trips/start",
        data={
            "csrf_token": "test-csrf",
            "origin": "Дом",
            "departed_at": "2026-09-03T09:00",
        },
    )
    auth_client.post(
        "/trips/finish",
        data={
            "csrf_token": "test-csrf",
            "destination": "Парк",
            "arrived_at": "2026-09-03T09:30",
            "transport_type": "scooter",
        },
    )
    with app.app_context():
        trip = db.session.scalar(db.select(Trip))
        assert trip is not None
        assert trip.cost == 0


def test_taxi_tariff_is_selected_from_list(app: Flask, auth_client) -> None:
    """Такси сохраняет выбранный тариф и общую стоимость поездки."""

    auth_client.post(
        "/trips/start",
        data={
            "csrf_token": "test-csrf",
            "origin": "Дом",
            "departed_at": "2026-09-03T09:00",
        },
    )
    auth_client.post(
        "/trips/finish",
        data={
            "csrf_token": "test-csrf",
            "destination": "Парк",
            "arrived_at": "2026-09-03T09:30",
            "transport_type": "taxi",
            "cost": "650",
            "taxi_tariff": "Комфорт+",
        },
    )
    with app.app_context():
        trip = db.session.scalar(db.select(Trip))
        assert trip is not None
        assert trip.cost == 650
        assert trip.taxi_tariff == "Комфорт+"


def test_existing_taxi_cost_is_migrated(tmp_path: Path) -> None:
    """Общая стоимость подхватывает значения из старой колонки такси."""

    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """CREATE TABLE user (
                id INTEGER PRIMARY KEY,
                yandex_id VARCHAR NOT NULL,
                display_name VARCHAR NOT NULL,
                email VARCHAR,
                avatar_url VARCHAR,
                created_at DATETIME NOT NULL
            )"""
        )
        connection.execute(
            "CREATE TABLE trip (id INTEGER PRIMARY KEY, taxi_cost FLOAT)"
        )
        connection.execute("INSERT INTO trip (taxi_cost) VALUES (750)")

    class LegacyConfig(Config):
        """Конфигурация приложения с имитацией старой SQLite-базы."""

        model_config = SettingsConfigDict(env_file=None, populate_by_name=True)
        environment: Literal["testing"] = "testing"
        secret_key: SecretStr = SecretStr("migration-test")
        database_url: str = f"sqlite:///{database_path}"

    application = create_app(LegacyConfig)
    result = application.test_cli_runner().invoke(args=["db", "upgrade"])
    assert result.exit_code == 0, result.output
    with application.app_context():
        columns = {
            row[1] for row in db.session.execute(text("PRAGMA table_info(trip)")).all()
        }
        user_columns = {
            row[1] for row in db.session.execute(text("PRAGMA table_info(user)")).all()
        }
        migrated_cost = db.session.execute(
            text("SELECT cost FROM trip WHERE id = 1")
        ).scalar_one()
        assert "cost" in columns
        assert "timezone" in user_columns
        assert "terms_version" in user_columns
        assert "terms_accepted_at" in user_columns
        assert migrated_cost == 750


def test_migrations_create_a_fresh_database(tmp_path: Path) -> None:
    """Новая база полностью создаётся только явной миграцией."""

    database_path = tmp_path / "fresh.sqlite3"

    class FreshConfig(Config):
        """Изолированная конфигурация для проверки миграций."""

        model_config = SettingsConfigDict(env_file=None, populate_by_name=True)
        environment: Literal["testing"] = "testing"
        secret_key: SecretStr = SecretStr("migration-test")
        database_url: str = f"sqlite:///{database_path}"

    application = create_app(FreshConfig)
    result = application.test_cli_runner().invoke(args=["db", "upgrade"])
    assert result.exit_code == 0, result.output
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"alembic_version", "user", "place", "trip", "active_trip"} <= tables


def test_health_and_readiness_endpoints(client) -> None:
    """Оркестратор может отдельно проверить процесс и базу данных."""

    health = client.get("/healthz")
    readiness = client.get("/readyz")
    assert health.status_code == 200
    assert health.json == {"status": "ok"}
    assert readiness.status_code == 200
    assert readiness.json == {"status": "ok"}
    assert health.headers["Cache-Control"] == "no-store"


def test_active_trip_can_be_cleared(app: Flask, auth_client, user) -> None:
    """Пользователь может отменить сохранённую начальную точку."""

    start_response = auth_client.post(
        "/trips/start",
        data={
            "csrf_token": "test-csrf",
            "origin": "Вокзал",
            "departed_at": "2026-09-03T11:00",
        },
        follow_redirects=True,
    )
    assert 'class="toast ' not in start_response.text
    response = auth_client.post(
        "/trips/active/clear",
        data={"csrf_token": "test-csrf"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert 'class="toast ' not in response.text
    with app.app_context():
        assert db.session.scalar(db.select(ActiveTrip)) is None
        assert db.session.scalar(db.select(Trip)) is None


def test_place_names_are_deduplicated(app: Flask, user) -> None:
    """Разный регистр и лишние пробелы не создают дубликаты мест."""

    with app.app_context():
        first = get_or_create_place(user.id, "Кофейня Север")
        second = get_or_create_place(user.id, "  кофейня   север ")
        db.session.commit()
        assert first.id == second.id
        assert db.session.query(Place).count() == 1


def test_place_suggestions_ignore_cyrillic_case(app: Flask, auth_client, user) -> None:
    """Поиск мест не зависит от регистра, включая кириллицу."""

    with app.app_context():
        get_or_create_place(user.id, "Кофейня Север")
        db.session.commit()

    response = auth_client.get("/api/places?q=КОФЕЙНЯ")
    assert response.status_code == 200
    assert [place["name"] for place in response.json] == ["Кофейня Север"]


def test_metro_line_is_saved_for_future_suggestions(app: Flask, auth_client) -> None:
    """Ветка завершённой поездки попадает в подсказки следующих записей."""

    auth_client.post(
        "/trips/start",
        data={
            "csrf_token": "test-csrf",
            "origin": "Дом",
            "departed_at": "2026-09-03T09:00",
        },
    )
    auth_client.post(
        "/trips/finish",
        data={
            "csrf_token": "test-csrf",
            "destination": "Работа",
            "arrived_at": "2026-09-03T09:30",
            "transport_type": "metro",
            "transport_detail": "Сокольническая",
        },
    )

    response = auth_client.get("/api/metro-lines?q=СОКОЛЬ")
    assert response.status_code == 200
    assert response.json == [{"name": "Сокольническая"}]


def test_route_uses_average_duration(app: Flask, auth_client, user) -> None:
    """Расчёт возвращает среднее по сохранённым отрезкам."""

    with app.app_context():
        origin = get_or_create_place(user.id, "Дом")
        destination = get_or_create_place(user.id, "Офис")
        db.session.flush()
        for start, end, transport in [
            ("08:00", "08:30", "metro"),
            ("09:00", "09:40", "metro"),
        ]:
            db.session.add(
                Trip(
                    user_id=user.id,
                    origin_id=origin.id,
                    destination_id=destination.id,
                    departed_at=datetime.fromisoformat(f"2026-09-03T{start}"),
                    arrived_at=datetime.fromisoformat(f"2026-09-03T{end}"),
                    transport_type=transport,
                )
            )
        db.session.commit()

    response = auth_client.post(
        "/api/calculate",
        json={"points": ["Дом", "Офис"]},
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert response.status_code == 200
    assert response.json["total_minutes"] == 35
    assert response.json["complete"] is True
    assert response.json["segments"][0]["samples"] == 2


def test_route_rejects_malformed_and_excessive_points(auth_client) -> None:
    """API возвращает 400 вместо 500 и ограничивает сложность расчёта."""

    headers = {"X-CSRF-Token": "test-csrf"}
    for points in (None, 123, {}, ["A", 42]):
        response = auth_client.post(
            "/api/calculate", json={"points": points}, headers=headers
        )
        assert response.status_code == 400
    response = auth_client.post(
        "/api/calculate",
        json={"points": [f"P{index}" for index in range(21)]},
        headers=headers,
    )
    assert response.status_code == 400


def test_incomplete_route_does_not_report_average_speed(
    app: Flask, auth_client, user
) -> None:
    """Скорость не выглядит итоговой, пока известно не всё время маршрута."""

    with app.app_context():
        first = get_or_create_place(user.id, "A")
        second = get_or_create_place(user.id, "B")
        third = get_or_create_place(user.id, "C")
        first.latitude, first.longitude = 55.0, 37.0
        second.latitude, second.longitude = 55.1, 37.1
        third.latitude, third.longitude = 55.2, 37.2
        db.session.flush()
        db.session.add(
            Trip(
                user_id=user.id,
                origin_id=first.id,
                destination_id=second.id,
                departed_at=datetime.fromisoformat("2026-09-03T08:00"),
                arrived_at=datetime.fromisoformat("2026-09-03T08:30"),
                transport_type="car",
            )
        )
        db.session.commit()

    response = auth_client.post(
        "/api/calculate",
        json={"points": ["A", "B", "C"]},
        headers={"X-CSRF-Token": "test-csrf"},
    )
    assert response.status_code == 200
    assert response.json["complete"] is False
    assert (
        response.json["total_distance_km"] > response.json["segments"][0]["distance_km"]
    )
    assert response.json["average_speed_kmh"] is None


def test_route_result_is_a_separate_page_with_geo_summary(
    app: Flask, auth_client, user
) -> None:
    """Форма ведёт на отдельную страницу с треком, расстоянием и скоростью."""

    with app.app_context():
        origin = get_or_create_place(user.id, "Дом")
        origin.latitude, origin.longitude = 55.751244, 37.618423
        destination = get_or_create_place(user.id, "Офис")
        destination.latitude, destination.longitude = 55.760186, 37.618711
        db.session.flush()
        db.session.add(
            Trip(
                user_id=user.id,
                origin_id=origin.id,
                destination_id=destination.id,
                departed_at=datetime.fromisoformat("2026-09-03T08:00"),
                arrived_at=datetime.fromisoformat("2026-09-03T08:12"),
                transport_type="walk",
            )
        )
        db.session.commit()

    form_page = auth_client.get("/calculate")
    assert 'action="/calculate/result"' in form_page.text
    assert 'name="points"' in form_page.text

    response = auth_client.get("/calculate/result?points=Дом&points=Офис")
    assert response.status_code == 200
    assert "data-route-canvas" in response.text
    assert "ХОД · МОЙ МАРШРУТ" not in response.text
    assert "Изменить маршрут" not in response.text
    assert "Пешком" in response.text
    assert "км/ч" in response.text
    assert "Путь рассчитан как сумма расстояний" in response.text
    assert "Схема построена по порядку точек" not in response.text


def test_route_result_falls_back_to_schematic_track(auth_client) -> None:
    """Маршрут без координат всё равно получает подписанную схему."""

    response = auth_client.get("/calculate/result?points=А&points=Б")
    assert response.status_code == 200
    assert "Сейчас схема передаёт порядок остановок" in response.text
    assert "Пока нет записанных поездок" in response.text


def test_csrf_is_required(auth_client) -> None:
    """Изменяющий запрос без CSRF-токена отклоняется."""

    response = auth_client.post("/api/calculate", json={"points": ["A", "B"]})
    assert response.status_code == 400


def test_yandex_avatar_uses_large_profile_image() -> None:
    """Портрет строится из идентификатора, который вернул Яндекс."""

    assert yandex_avatar_url({"default_avatar_id": "portrait-42"}) == (
        "https://avatars.yandex.net/get-yapic/portrait-42/islands-200"
    )


def test_yandex_callback_saves_avatar(app: Flask, client, monkeypatch) -> None:
    """OAuth callback сохраняет портрет из ответа Яндекс ID."""

    class ProfileResponse:
        """Минимальный ответ API профиля для теста."""

        def raise_for_status(self) -> None:
            """Имитировать успешный HTTP-ответ."""

        def json(self) -> dict[str, object]:
            """Вернуть профиль с идентификатором портрета."""

            return {
                "id": "99",
                "display_name": "Анна",
                "default_email": "anna@example.ru",
                "default_avatar_id": "avatar-99",
            }

    with app.app_context():
        yandex = oauth.create_client("yandex")
        monkeypatch.setattr(
            yandex, "authorize_access_token", lambda: {"access_token": "token"}
        )
        monkeypatch.setattr(yandex, "get", lambda *_args, **_kwargs: ProfileResponse())
    with client.session_transaction() as session:
        session["pending_terms_version"] = "1.0"
        session["pending_terms_accepted_at"] = "2026-09-11T10:00:00+00:00"

    response = client.get("/auth/callback")
    assert response.status_code == 302
    with app.app_context():
        account = db.session.scalar(db.select(User).where(User.yandex_id == "99"))
        assert account is not None
        assert account.avatar_url.endswith("/avatar-99/islands-200")
        assert account.terms_version == "1.0"
        assert account.terms_accepted_at is not None


def test_yandex_callback_failure_returns_to_home(
    app: Flask, client, monkeypatch
) -> None:
    """Ошибка или отмена OAuth не превращается в страницу 500."""

    from authlib.integrations.base_client.errors import OAuthError

    with app.app_context():
        yandex = oauth.create_client("yandex")

        def fail_login():
            raise OAuthError(error="access_denied")

        monkeypatch.setattr(yandex, "authorize_access_token", fail_login)
    with client.session_transaction() as session:
        session["pending_terms_version"] = "1.0"
        session["pending_terms_accepted_at"] = "2026-09-11T10:00:00+00:00"

    response = client.get("/auth/callback", follow_redirects=True)
    assert response.status_code == 200
    assert "Не удалось войти через Яндекс" in response.text


def test_sections_and_place_metadata(app: Flask, auth_client, user) -> None:
    """Новые разделы открываются, а данные места сохраняются."""

    response = auth_client.post(
        "/places",
        data={
            "csrf_token": "test-csrf",
            "name": "Парк",
            "latitude": "55.7512",
            "longitude": "37.6184",
            "description": "У фонтана",
            "marker_color": "#22aa66",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        place = db.session.scalar(db.select(Place))
        assert place is not None
        assert place.address is None
        assert place.latitude == 55.7512
        assert place.description == "У фонтана"
        assert place.marker_color == "#22aa66"

    places_page = auth_client.get("/places")
    assert 'name="address"' not in places_page.text
    assert 'name="latitude" type="hidden"' in places_page.text
    assert "Указать точку на карте" in places_page.text

    for path, expected_text in [
        ("/trips", "Все поездки"),
        ("/places", "Места"),
        ("/map", "journey-map"),
        ("/profile", "Статистика поездок"),
    ]:
        page = auth_client.get(path)
        assert page.status_code == 200
        assert expected_text in page.text

    map_page = auth_client.get("/map")
    assert "cdn.jsdelivr.net/npm/ol@v10.6.1" in map_page.text
    assert "leaflet" not in map_page.text.casefold()
    assert "OpenStreetMap" not in map_page.text
    map_script = auth_client.get("/static/js/app.js")
    assert "World_Imagery/MapServer/tile" in map_script.text
    assert "new ol.Map" in map_script.text
    assert "World_Street_Map" not in map_script.text
    assert "tile.openstreetmap.org" not in map_script.text


def test_user_cannot_read_or_update_another_users_places(
    app: Flask, auth_client
) -> None:
    """Выборки и изменение мест всегда ограничены владельцем."""

    with app.app_context():
        other = User(yandex_id="other", display_name="Другой")
        db.session.add(other)
        db.session.flush()
        secret_place = get_or_create_place(other.id, "Секретное место")
        db.session.commit()
        place_id = secret_place.id

    suggestions = auth_client.get("/api/places?q=Секретное")
    assert suggestions.status_code == 200
    assert suggestions.json == []
    update = auth_client.post(
        f"/places/{place_id}",
        data={"csrf_token": "test-csrf", "name": "Украденное место"},
    )
    assert update.status_code == 404


def test_place_rejects_non_finite_coordinates(auth_client) -> None:
    """NaN и Infinity не попадают в геоданные и расчёты маршрутов."""

    for latitude, longitude in (("nan", "37"), ("55", "inf")):
        response = auth_client.post(
            "/places",
            data={
                "csrf_token": "test-csrf",
                "name": f"Точка {latitude} {longitude}",
                "latitude": latitude,
                "longitude": longitude,
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "должна быть от" in response.text


def test_user_can_delete_one_or_all_trips(app: Flask, auth_client, user) -> None:
    """Удаление истории затрагивает только выбранные пользователем записи."""

    with app.app_context():
        origin = get_or_create_place(user.id, "A")
        destination = get_or_create_place(user.id, "B")
        db.session.flush()
        trips = [
            Trip(
                user_id=user.id,
                origin_id=origin.id,
                destination_id=destination.id,
                departed_at=datetime.fromisoformat(f"2026-09-0{day}T08:00"),
                arrived_at=datetime.fromisoformat(f"2026-09-0{day}T08:30"),
                transport_type="walk",
            )
            for day in (1, 2)
        ]
        db.session.add_all(trips)
        db.session.commit()
        first_id = trips[0].id

    response = auth_client.post(
        f"/trips/{first_id}/delete", data={"csrf_token": "test-csrf"}
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Trip.id))) == 1

    response = auth_client.post(
        "/trips/delete-all",
        data={"csrf_token": "test-csrf", "confirm_delete": "1"},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Trip.id))) == 0
        assert db.session.scalar(db.select(db.func.count(Place.id))) == 2


def test_user_can_delete_account_and_all_personal_data(
    app: Flask, auth_client, user
) -> None:
    """Самообслуживание удаляет профиль, поездки, места и активный маршрут."""

    auth_client.post(
        "/trips/start",
        data={
            "csrf_token": "test-csrf",
            "origin": "Дом",
            "departed_at": "2026-09-03T09:00",
        },
    )
    rejected = auth_client.post(
        "/auth/account/delete",
        data={"csrf_token": "test-csrf", "confirmation": "удалить"},
    )
    assert rejected.status_code == 302
    with app.app_context():
        assert db.session.get(User, user.id) is not None

    deleted = auth_client.post(
        "/auth/account/delete",
        data={"csrf_token": "test-csrf", "confirmation": "УДАЛИТЬ"},
        follow_redirects=True,
    )
    assert deleted.status_code == 200
    assert "Аккаунт и все связанные данные удалены" in deleted.text
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 0
        assert db.session.scalar(db.select(db.func.count(ActiveTrip.id))) == 0
        assert db.session.scalar(db.select(db.func.count(Place.id))) == 0
