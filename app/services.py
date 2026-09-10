"""Прикладная логика записи и расчёта маршрутов."""

from collections import Counter
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
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
    total_distance_km = 0.0
    complete = True

    normalized_names = [normalize_place(name) for name in point_names]
    saved_places = db.session.scalars(
        select(Place).where(
            Place.user_id == user_id,
            Place.normalized_name.in_(normalized_names),
        )
    ).all()
    places_by_name = {place.normalized_name: place for place in saved_places}
    route_points = [
        {
            "name": name,
            "latitude": places_by_name.get(normalized).latitude
            if places_by_name.get(normalized)
            else None,
            "longitude": places_by_name.get(normalized).longitude
            if places_by_name.get(normalized)
            else None,
        }
        for name, normalized in zip(point_names, normalized_names)
    ]

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
        common_detail = Counter(
            trip.transport_detail for trip in trips if trip.transport_detail
        ).most_common(1)
        origin_place = places_by_name.get(origin)
        destination_place = places_by_name.get(destination)
        distance_km = _distance_between(origin_place, destination_place)
        if distance_km is not None:
            total_distance_km += distance_km
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
                "transport_detail": common_detail[0][0] if common_detail else None,
                "distance_km": round(distance_km, 1) if distance_km is not None else None,
                "speed_kmh": round(distance_km / (average / 60), 1)
                if distance_km is not None and average > 0
                else None,
            }
        )

    has_full_distance = all(
        point["latitude"] is not None and point["longitude"] is not None
        for point in route_points
    )
    return {
        "points": route_points,
        "segments": segments,
        "total_minutes": total_minutes,
        "total_distance_km": round(total_distance_km, 1) if has_full_distance else None,
        "average_speed_kmh": round(total_distance_km / (total_minutes / 60), 1)
        if has_full_distance and total_minutes > 0
        else None,
        "complete": complete,
        "has_full_track": has_full_distance,
    }


def _distance_between(origin: Place | None, destination: Place | None) -> float | None:
    """Вернуть расстояние по дуге Земли между двумя сохранёнными местами."""

    if (
        origin is None
        or destination is None
        or origin.latitude is None
        or origin.longitude is None
        or destination.latitude is None
        or destination.longitude is None
    ):
        return None
    latitude_delta = radians(destination.latitude - origin.latitude)
    longitude_delta = radians(destination.longitude - origin.longitude)
    start_latitude = radians(origin.latitude)
    end_latitude = radians(destination.latitude)
    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(start_latitude) * cos(end_latitude) * sin(longitude_delta / 2) ** 2
    )
    return 6371.0088 * 2 * asin(sqrt(haversine))


def parse_local_datetime(value: str) -> datetime:
    """Преобразовать значение HTML datetime-local в дату и время."""

    return datetime.fromisoformat(value)
