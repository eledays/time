"""Прикладная логика записи и расчёта маршрутов."""

from collections import Counter
from datetime import datetime
from itertools import pairwise
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

MAX_ROUTE_SEARCH_STATES = 5_000
MAX_ROUTE_CANDIDATES = 1_000


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
    places_by_id = {place.id: place for place in saved_places}
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

    place_ids = list(places_by_id)
    relevant_trips = (
        db.session.scalars(
            select(Trip)
            .where(
                Trip.user_id == user_id,
                Trip.origin_id.in_(place_ids),
                Trip.destination_id.in_(place_ids),
            )
            .order_by(Trip.id)
        ).all()
        if place_ids
        else []
    )
    trips_by_route: dict[tuple[str, str], list[Trip]] = {}
    for trip in relevant_trips:
        route_key = (
            places_by_id[trip.origin_id].normalized_name,
            places_by_id[trip.destination_id].normalized_name,
        )
        trips_by_route.setdefault(route_key, []).append(trip)

    for origin_name, destination_name in pairwise(point_names):
        origin = normalize_place(origin_name)
        destination = normalize_place(destination_name)
        origin_place = places_by_name.get(origin)
        destination_place = places_by_name.get(destination)
        distance_km = _distance_between(origin_place, destination_place)
        if distance_km is not None:
            total_distance_km += distance_km
        trips = trips_by_route.get((origin, destination), [])
        if not trips:
            complete = False
            segments.append(
                {
                    "from": origin_name,
                    "to": destination_name,
                    "known": False,
                    "distance_km": round(distance_km, 1)
                    if distance_km is not None
                    else None,
                }
            )
            continue

        common_transport = Counter(trip.transport_type for trip in trips).most_common(
            1
        )[0][0]
        representative_trips = [
            trip for trip in trips if trip.transport_type == common_transport
        ]
        durations = [trip.duration_minutes for trip in representative_trips]
        average = round(sum(durations) / len(durations))
        common_detail = Counter(
            trip.transport_detail
            for trip in representative_trips
            if trip.transport_detail
        ).most_common(1)
        total_minutes += average
        segments.append(
            {
                "from": origin_name,
                "to": destination_name,
                "known": True,
                "minutes": average,
                "min_minutes": min(durations),
                "max_minutes": max(durations),
                "samples": len(representative_trips),
                "transport": TRANSPORT_LABELS.get(common_transport, "Другое"),
                "transport_detail": common_detail[0][0] if common_detail else None,
                "distance_km": round(distance_km, 1)
                if distance_km is not None
                else None,
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
        if complete and has_full_distance and total_minutes > 0
        else None,
        "complete": complete,
        "has_full_track": has_full_distance,
    }


def calculate_route_variants(
    user_id: int,
    origin_name: str,
    destination_name: str,
    *,
    max_intermediate_points: int,
    max_variants: int,
) -> dict[str, Any]:
    """Найти ограниченный набор составных маршрутов по истории пользователя."""

    places = db.session.scalars(
        select(Place).where(Place.user_id == user_id).order_by(Place.id)
    ).all()
    places_by_name = {place.normalized_name: place for place in places}
    origin = places_by_name.get(normalize_place(origin_name))
    destination = places_by_name.get(normalize_place(destination_name))
    response: dict[str, Any] = {
        "origin": origin.name if origin else origin_name,
        "destination": destination.name if destination else destination_name,
        "variants": [],
        "max_intermediate_points": max_intermediate_points,
        "max_variants": max_variants,
        "search_truncated": False,
    }
    if origin is None or destination is None:
        return response

    trips = db.session.scalars(
        select(Trip).where(Trip.user_id == user_id).order_by(Trip.id)
    ).all()
    grouped: dict[tuple[int, int, str], list[Trip]] = {}
    for trip in trips:
        grouped.setdefault(
            (trip.origin_id, trip.destination_id, trip.transport_type), []
        ).append(trip)

    places_by_id = {place.id: place for place in places}
    adjacency: dict[int, list[dict[str, Any]]] = {}
    for (origin_id, destination_id, transport_type), observations in grouped.items():
        start = places_by_id.get(origin_id)
        finish = places_by_id.get(destination_id)
        if start is None or finish is None:
            continue
        durations = [trip.duration_minutes for trip in observations]
        average = round(sum(durations) / len(durations))
        details = Counter(
            trip.transport_detail for trip in observations if trip.transport_detail
        ).most_common(1)
        distance_km = _distance_between(start, finish)
        edge = {
            "from_id": origin_id,
            "to_id": destination_id,
            "from": start.name,
            "to": finish.name,
            "known": True,
            "minutes": average,
            "min_minutes": min(durations),
            "max_minutes": max(durations),
            "samples": len(observations),
            "transport_key": transport_type,
            "transport": TRANSPORT_LABELS.get(transport_type, "Другое"),
            "transport_detail": details[0][0] if details else None,
            "distance_km": round(distance_km, 1)
            if distance_km is not None
            else None,
            "speed_kmh": round(distance_km / (average / 60), 1)
            if distance_km is not None and average > 0
            else None,
        }
        adjacency.setdefault(origin_id, []).append(edge)

    for edges in adjacency.values():
        edges.sort(
            key=lambda edge: (
                edge["minutes"],
                normalize_place(edge["to"]),
                edge["transport_key"],
            )
        )

    max_edges = max_intermediate_points + 1
    found: list[list[dict[str, Any]]] = []
    states: list[tuple[int, list[dict[str, Any]], frozenset[int]]] = [
        (origin.id, [], frozenset({origin.id}))
    ]
    inspected_states = 0
    while (
        states
        and inspected_states < MAX_ROUTE_SEARCH_STATES
        and len(found) < MAX_ROUTE_CANDIDATES
    ):
        current_id, path, visited = states.pop()
        inspected_states += 1
        for edge in reversed(adjacency.get(current_id, [])):
            next_id = edge["to_id"]
            next_path = [*path, edge]
            if next_id == destination.id and next_path:
                found.append(next_path)
                continue
            if len(next_path) >= max_edges or next_id in visited:
                continue
            states.append((next_id, next_path, visited | {next_id}))
    response["search_truncated"] = bool(states) or len(found) >= MAX_ROUTE_CANDIDATES

    unique: dict[tuple[tuple[int, int, str], ...], list[dict[str, Any]]] = {}
    for path in found:
        signature = tuple(
            (edge["from_id"], edge["to_id"], edge["transport_key"])
            for edge in path
        )
        unique.setdefault(signature, path)

    variants = [_route_variant(path, places_by_id) for path in unique.values()]
    variants.sort(
        key=lambda variant: (
            variant["total_minutes"],
            len(variant["segments"]),
            -variant["observations"],
            tuple(point["name"] for point in variant["points"]),
        )
    )
    response["variants"] = variants[:max_variants]
    response["search_truncated"] = response["search_truncated"] or len(variants) > max_variants
    return response


def _route_variant(
    path: list[dict[str, Any]], places_by_id: dict[int, Place]
) -> dict[str, Any]:
    """Собрать итоговые показатели одного найденного варианта."""

    point_ids = [path[0]["from_id"], *(edge["to_id"] for edge in path)]
    points = [
        {
            "name": places_by_id[place_id].name,
            "latitude": places_by_id[place_id].latitude,
            "longitude": places_by_id[place_id].longitude,
        }
        for place_id in point_ids
    ]
    total_minutes = sum(edge["minutes"] for edge in path)
    has_full_track = all(
        point["latitude"] is not None and point["longitude"] is not None
        for point in points
    )
    total_distance_km = (
        round(sum(edge["distance_km"] for edge in path), 1)
        if has_full_track
        else None
    )
    return {
        "points": points,
        "segments": path,
        "total_minutes": total_minutes,
        "total_distance_km": total_distance_km,
        "average_speed_kmh": round(total_distance_km / (total_minutes / 60), 1)
        if total_distance_km is not None and total_minutes > 0
        else None,
        "complete": True,
        "has_full_track": has_full_track,
        "observations": sum(edge["samples"] for edge in path),
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

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError("Ожидается локальное время без часового пояса")
    return parsed
