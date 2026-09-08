"""Прикладная логика записи и расчёта маршрутов."""

from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.extensions import db
from app.models import Place, Trip

TRANSPORT_LABELS = {
    "walk": "Пешком",
    "bus": "Автобус",
    "metro": "Метро",
    "bike": "Велосипед",
    "ebike": "Электровелосипед",
    "scooter": "Самокат",
    "taxi": "Такси",
    "car": "Автомобиль",
    "other": "Другой",
}

TAXI_TARIFFS = ("Эконом", "Комфорт", "Комфорт+", "Бизнес", "Другое")

TIMEZONE_CHOICES = {
    "Europe/Kaliningrad": "Калининград",
    "Europe/Moscow": "Москва",
    "Europe/Samara": "Самара",
    "Asia/Yekaterinburg": "Екатеринбург",
    "Asia/Omsk": "Омск",
    "Asia/Novosibirsk": "Новосибирск",
    "Asia/Krasnoyarsk": "Красноярск",
    "Asia/Irkutsk": "Иркутск",
    "Asia/Yakutsk": "Якутск",
    "Asia/Vladivostok": "Владивосток",
    "Asia/Magadan": "Магадан",
    "Asia/Kamchatka": "Камчатка",
    "UTC": "UTC",
}


def normalize_place(value: str) -> str:
    """Нормализовать пробелы и регистр названия места."""

    return " ".join(value.strip().casefold().split())


def get_or_create_place(user_id: int, name: str) -> Place:
    """Найти место пользователя или создать новое."""

    clean_name = " ".join(name.strip().split())
    normalized = normalize_place(clean_name)
    place = db.session.scalar(
        select(Place).where(
            Place.user_id == user_id, Place.normalized_name == normalized
        )
    )
    if place is None:
        place = Place(user_id=user_id, name=clean_name, normalized_name=normalized)
        db.session.add(place)
        db.session.flush()
    return place


def calculate_route(user_id: int, point_names: list[str]) -> dict[str, Any]:
    """Рассчитать маршрут по средним значениям сохранённых поездок."""

    segments: list[dict[str, Any]] = []
    total_minutes = 0
    complete = True

    for origin_name, destination_name in zip(point_names, point_names[1:]):
        origin = normalize_place(origin_name)
        destination = normalize_place(destination_name)
        trips = db.session.scalars(
            select(Trip).where(
                Trip.user_id == user_id,
                Trip.origin.has(Place.normalized_name == origin),
                Trip.destination.has(Place.normalized_name == destination),
            )
        ).all()
        if not trips:
            complete = False
            segments.append(
                {"from": origin_name, "to": destination_name, "known": False}
            )
            continue

        durations = [trip.duration_minutes for trip in trips]
        average = round(sum(durations) / len(durations))
        common_transport = Counter(trip.transport_type for trip in trips).most_common(1)[0][0]
        total_minutes += average
        segments.append(
            {
                "from": origin_name,
                "to": destination_name,
                "known": True,
                "minutes": average,
                "min_minutes": min(durations),
                "max_minutes": max(durations),
                "samples": len(trips),
                "transport": TRANSPORT_LABELS.get(common_transport, "Другое"),
            }
        )

    return {
        "segments": segments,
        "total_minutes": total_minutes,
        "complete": complete,
    }


def parse_local_datetime(value: str) -> datetime:
    """Преобразовать значение HTML datetime-local в дату и время."""

    return datetime.fromisoformat(value)
