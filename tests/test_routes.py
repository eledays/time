"""Интеграционные тесты страниц и API."""

from datetime import datetime

from flask import Flask

from app.extensions import db
from app.models import Place, Trip
from app.services import get_or_create_place


def test_home_is_available_without_login(client) -> None:
    """Главная показывает приглашение войти анонимному посетителю."""

    response = client.get("/")
    assert response.status_code == 200
    assert "Войти через Яндекс" in response.text


def test_calculator_requires_login(client) -> None:
    """Расчёт маршрута недоступен без сессии."""

    response = client.get("/calculate")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")


def test_trip_is_saved_with_bus_number(app: Flask, auth_client, user) -> None:
    """Сохранение поездки создаёт места и оставляет номер автобуса."""

    response = auth_client.post(
        "/trips",
        data={
            "csrf_token": "test-csrf",
            "origin": "  Дом  ",
            "destination": "Парк",
            "departed_at": "2026-09-03T09:00",
            "arrived_at": "2026-09-03T09:36",
            "transport_type": "bus",
            "transport_detail": "39",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        trip = db.session.scalar(db.select(Trip))
        assert trip is not None
        assert trip.duration_minutes == 36
        assert trip.transport_detail == "39"
        assert trip.origin.name == "Дом"
        assert db.session.query(Place).count() == 2


def test_place_names_are_deduplicated(app: Flask, user) -> None:
    """Разный регистр и лишние пробелы не создают дубликаты мест."""

    with app.app_context():
        first = get_or_create_place(user.id, "Кофейня Север")
        second = get_or_create_place(user.id, "  кофейня   север ")
        db.session.commit()
        assert first.id == second.id
        assert db.session.query(Place).count() == 1


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


def test_csrf_is_required(auth_client) -> None:
    """Изменяющий запрос без CSRF-токена отклоняется."""

    response = auth_client.post("/api/calculate", json={"points": ["A", "B"]})
    assert response.status_code == 400

