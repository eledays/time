"""Страницы, JSON API и сохранение поездок."""

import re
from collections import Counter

from flask import flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import select

from app.auth.helpers import login_required
from app.extensions import db
from app.main import bp
from app.models import ActiveTrip, Place, Trip
from app.services import (
    TRANSPORT_LABELS,
    calculate_route,
    get_or_create_place,
    normalize_place,
    parse_local_datetime,
)

COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")


@bp.get("/")
def index():
    """Показать форму записи поездки."""

    active_trip = None
    if g.user:
        active_trip = db.session.scalar(
            select(ActiveTrip).where(ActiveTrip.user_id == g.user.id)
        )
    return render_template(
        "index.html",
        active_trip=active_trip,
        transport_labels=TRANSPORT_LABELS,
    )


@bp.post("/trips/start")
@login_required
def start_trip():
    """Сохранить начальную точку и время активной поездки."""

    origin_name = request.form.get("origin", "").strip()
    try:
        departed_at = parse_local_datetime(request.form.get("departed_at", ""))
    except ValueError:
        flash("Проверьте время отправления", "error")
        return redirect(url_for("main.index"))

    if not origin_name:
        flash("Укажите начальную точку", "error")
        return redirect(url_for("main.index"))
    active_trip = db.session.scalar(
        select(ActiveTrip).where(ActiveTrip.user_id == g.user.id)
    )
    if active_trip is not None:
        flash("Сначала завершите или очистите активную поездку", "warning")
        return redirect(url_for("main.index"))

    origin = get_or_create_place(g.user.id, origin_name)
    db.session.add(
        ActiveTrip(user_id=g.user.id, origin_id=origin.id, departed_at=departed_at)
    )
    db.session.commit()
    flash("Начальная точка сохранена. Счастливого пути!", "success")
    return redirect(url_for("main.index"))


@bp.post("/trips/finish")
@login_required
def finish_trip():
    """Дополнить активную поездку конечной точкой и сохранить маршрут."""

    active_trip = db.session.scalar(
        select(ActiveTrip).where(ActiveTrip.user_id == g.user.id)
    )
    if active_trip is None:
        flash("Сначала задайте начальную точку", "warning")
        return redirect(url_for("main.index"))

    destination_name = request.form.get("destination", "").strip()
    transport_type = request.form.get("transport_type", "")
    try:
        arrived_at = parse_local_datetime(request.form.get("arrived_at", ""))
    except ValueError:
        flash("Проверьте время прибытия", "error")
        return redirect(url_for("main.index"))
    if not destination_name or active_trip.origin.normalized_name == normalize_place(destination_name):
        flash("Укажите конечную точку, отличную от начальной", "error")
        return redirect(url_for("main.index"))
    if transport_type not in TRANSPORT_LABELS:
        flash("Выберите тип перемещения", "error")
        return redirect(url_for("main.index"))
    if arrived_at <= active_trip.departed_at:
        flash("Прибытие должно быть позже отправления", "error")
        return redirect(url_for("main.index"))

    destination = get_or_create_place(g.user.id, destination_name)
    detail = request.form.get("transport_detail", "").strip() or None
    taxi_cost = None
    taxi_tariff = None
    if transport_type == "taxi":
        taxi_tariff = request.form.get("taxi_tariff", "").strip() or None
        try:
            cost_value = request.form.get("taxi_cost", "").strip()
            taxi_cost = float(cost_value) if cost_value else None
        except ValueError:
            flash("Стоимость такси должна быть числом", "error")
            return redirect(url_for("main.index"))

    trip = Trip(
        user_id=g.user.id,
        origin_id=active_trip.origin_id,
        destination_id=destination.id,
        departed_at=active_trip.departed_at,
        arrived_at=arrived_at,
        transport_type=transport_type,
        transport_detail=detail if transport_type in {"bus", "metro"} else None,
        taxi_cost=taxi_cost,
        taxi_tariff=taxi_tariff,
    )
    db.session.add(trip)
    db.session.delete(active_trip)
    db.session.commit()
    flash(f"Поездка сохранена · {trip.duration_minutes} мин", "success")
    return redirect(url_for("main.index"))


@bp.post("/trips/active/clear")
@login_required
def clear_active_trip():
    """Удалить сохранённую начальную точку без создания поездки."""

    active_trip = db.session.scalar(
        select(ActiveTrip).where(ActiveTrip.user_id == g.user.id)
    )
    if active_trip is not None:
        db.session.delete(active_trip)
        db.session.commit()
        flash("Начальная точка очищена", "success")
    return redirect(url_for("main.index"))


@bp.get("/calculate")
@login_required
def calculate():
    """Показать конструктор составного маршрута."""

    return render_template("calculate.html")


@bp.get("/trips")
@login_required
def trips():
    """Показать полную историю поездок пользователя."""

    trip_items = db.session.scalars(
        select(Trip)
        .where(Trip.user_id == g.user.id)
        .order_by(Trip.departed_at.desc())
    ).all()
    return render_template(
        "trips.html", trips=trip_items, transport_labels=TRANSPORT_LABELS
    )


@bp.get("/places")
@login_required
def places():
    """Показать сохранённые места пользователя."""

    place_items = db.session.scalars(
        select(Place)
        .where(Place.user_id == g.user.id)
        .order_by(Place.name)
    ).all()
    return render_template("places.html", places=place_items)


@bp.post("/places")
@login_required
def create_place():
    """Создать место и сохранить его дополнительные данные."""

    name = request.form.get("name", "").strip()
    if not name:
        flash("Введите название места", "error")
        return redirect(url_for("main.places"))
    place = get_or_create_place(g.user.id, name)
    if not _update_place_fields(place):
        db.session.rollback()
        return redirect(url_for("main.places"))
    db.session.commit()
    flash("Место сохранено", "success")
    return redirect(url_for("main.places"))


@bp.post("/places/<int:place_id>")
@login_required
def update_place(place_id: int):
    """Обновить принадлежащее пользователю место."""

    place = db.session.scalar(
        select(Place).where(Place.id == place_id, Place.user_id == g.user.id)
    )
    if place is None:
        return render_template("error.html", code=404, message="Место не найдено"), 404
    name = request.form.get("name", "").strip()
    if not name:
        flash("Название не может быть пустым", "error")
        return redirect(url_for("main.places"))
    normalized = normalize_place(name)
    duplicate = db.session.scalar(
        select(Place).where(
            Place.user_id == g.user.id,
            Place.normalized_name == normalized,
            Place.id != place.id,
        )
    )
    if duplicate:
        flash("Место с таким названием уже существует", "error")
        return redirect(url_for("main.places"))
    place.name = " ".join(name.split())
    place.normalized_name = normalized
    if not _update_place_fields(place):
        db.session.rollback()
        return redirect(url_for("main.places"))
    db.session.commit()
    flash("Изменения сохранены", "success")
    return redirect(url_for("main.places"))


@bp.get("/map")
@login_required
def map_view():
    """Показать места и поездки с координатами на карте."""

    places = db.session.scalars(
        select(Place).where(
            Place.user_id == g.user.id,
            Place.latitude.is_not(None),
            Place.longitude.is_not(None),
        )
    ).all()
    trips = db.session.scalars(
        select(Trip).where(Trip.user_id == g.user.id)
    ).all()
    mapped_ids = {place.id for place in places}
    map_data = {
        "places": [
            {
                "id": place.id,
                "name": place.name,
                "address": place.address,
                "lat": place.latitude,
                "lng": place.longitude,
                "color": place.marker_color,
            }
            for place in places
        ],
        "trips": [
            {
                "from": trip.origin_id,
                "to": trip.destination_id,
                "minutes": trip.duration_minutes,
            }
            for trip in trips
            if trip.origin_id in mapped_ids and trip.destination_id in mapped_ids
        ],
    }
    return render_template("map.html", map_data=map_data)


@bp.get("/profile")
@login_required
def profile():
    """Показать профиль Яндекса и личную статистику поездок."""

    trip_items = db.session.scalars(
        select(Trip).where(Trip.user_id == g.user.id)
    ).all()
    durations = [trip.duration_minutes for trip in trip_items]
    transport_counts = Counter(trip.transport_type for trip in trip_items)
    favorite = transport_counts.most_common(1)[0][0] if transport_counts else None
    place_count = db.session.scalar(
        select(db.func.count(Place.id)).where(Place.user_id == g.user.id)
    )
    stats = {
        "trips": len(trip_items),
        "minutes": sum(durations),
        "average": round(sum(durations) / len(durations)) if durations else 0,
        "days": len({trip.departed_at.date() for trip in trip_items}),
        "places": place_count or 0,
        "favorite": TRANSPORT_LABELS.get(favorite, "—") if favorite else "—",
    }
    return render_template("profile.html", stats=stats)


def _update_place_fields(place: Place) -> bool:
    """Проверить форму и записать метаданные места."""

    place.address = request.form.get("address", "").strip() or None
    place.description = request.form.get("description", "").strip() or None
    color = request.form.get("marker_color", "#111111")
    place.marker_color = color if COLOR_PATTERN.fullmatch(color) else "#111111"
    latitude = request.form.get("latitude", "").strip()
    longitude = request.form.get("longitude", "").strip()
    try:
        parsed_latitude = float(latitude) if latitude else None
        parsed_longitude = float(longitude) if longitude else None
    except ValueError:
        flash("Координаты должны быть числами", "error")
        return False
    if parsed_latitude is not None and not -90 <= parsed_latitude <= 90:
        flash("Широта должна быть от −90 до 90", "error")
        return False
    if parsed_longitude is not None and not -180 <= parsed_longitude <= 180:
        flash("Долгота должна быть от −180 до 180", "error")
        return False
    place.latitude = parsed_latitude
    place.longitude = parsed_longitude
    return True


@bp.get("/api/places")
@login_required
def places_api():
    """Вернуть до восьми мест для автодополнения."""

    query = request.args.get("q", "").strip()
    statement = select(Place).where(Place.user_id == g.user.id)
    if query:
        statement = statement.where(Place.name.ilike(f"%{query}%"))
    places = db.session.scalars(statement.order_by(Place.name).limit(8)).all()
    return jsonify([{"id": place.id, "name": place.name} for place in places])


@bp.post("/api/calculate")
@login_required
def calculate_api():
    """Вернуть оценку времени для последовательности точек."""

    payload = request.get_json(silent=True) or {}
    points = [str(point).strip() for point in payload.get("points", []) if str(point).strip()]
    if len(points) < 2:
        return jsonify({"error": "Добавьте минимум две точки"}), 400
    return jsonify(calculate_route(g.user.id, points))
