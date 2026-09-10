"""Интеграционные тесты страниц и API."""

import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask
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
    assert "Войти через Яндекс" in response.text
    assert "data-theme-toggle" not in response.text
    assert '<meta name="theme-color" content="#090909">' in response.text


def test_calculator_requires_login(client) -> None:
    """Расчёт маршрута недоступен без сессии."""

    response = client.get("/calculate")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")


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


def test_departure_time_is_hidden_by_default(auth_client) -> None:
    """Ручной выбор времени отправления открывается отдельной кнопкой."""

    page = auth_client.get("/")
    assert 'id="departed_at" name="departed_at" type="hidden"' in page.text
    assert 'data-time-dialog-open="departed_at"' in page.text
    assert 'aria-label="Время отправления не сейчас"' in page.text
    assert 'data-time-dialog="departed_at"' in page.text
    assert 'data-picker-date required disabled' in page.text
    assert 'data-picker-clock step="60" required disabled' in page.text
    assert 'class="material-symbols-rounded"' in page.text
    assert ">schedule</span>" in page.text
    for icon in ("add_circle", "route", "history", "location_on", "map", "person"):
        assert f'>{icon}</span><small>' in page.text
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

        TESTING = True
        SECRET_KEY = "migration-test"
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"

    application = create_app(LegacyConfig)
    with application.app_context():
        columns = {
            row[1]
            for row in db.session.execute(text("PRAGMA table_info(trip)")).all()
        }
        user_columns = {
            row[1]
            for row in db.session.execute(text("PRAGMA table_info(user)")).all()
        }
        migrated_cost = db.session.execute(
            text("SELECT cost FROM trip WHERE id = 1")
        ).scalar_one()
        assert "cost" in columns
        assert "timezone" in user_columns
        assert migrated_cost == 750


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
    assert 'data-route-canvas' in response.text
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
        monkeypatch.setattr(yandex, "authorize_access_token", lambda: {"access_token": "token"})
        monkeypatch.setattr(yandex, "get", lambda *_args, **_kwargs: ProfileResponse())

    response = client.get("/auth/callback")
    assert response.status_code == 302
    with app.app_context():
        account = db.session.scalar(db.select(User).where(User.yandex_id == "99"))
        assert account is not None
        assert account.avatar_url.endswith("/avatar-99/islands-200")


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

    for path, text in [
        ("/trips", "Все поездки"),
        ("/places", "Места"),
        ("/map", "journey-map"),
        ("/profile", "Статистика поездок"),
    ]:
        page = auth_client.get(path)
        assert page.status_code == 200
        assert text in page.text

    map_page = auth_client.get("/map")
    assert "cdn.jsdelivr.net/npm/ol@v10.6.1" in map_page.text
    assert "leaflet" not in map_page.text.casefold()
    assert "OpenStreetMap" not in map_page.text
    map_script = auth_client.get("/static/js/app.js")
    assert "World_Imagery/MapServer/tile" in map_script.text
    assert "new ol.Map" in map_script.text
    assert "World_Street_Map" not in map_script.text
    assert "tile.openstreetmap.org" not in map_script.text
