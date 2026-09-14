"""Страницы, JSON API и сохранение поездок."""

import re
from collections import Counter
from math import isfinite
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import (
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.auth.helpers import login_required
from app.extensions import db, limiter
from app.main import bp
from app.models import ActiveTrip, Place, Trip
from app.services import (
    TAXI_TARIFFS,
    TIMEZONE_CHOICES,
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
        taxi_tariffs=TAXI_TARIFFS,
    )


@bp.get("/terms")
def terms():
    """Показать действующее пользовательское соглашение."""

    return render_template("terms.html")


@bp.get("/privacy")
def privacy():
    """Показать политику обработки персональных данных."""

    return render_template("privacy.html")


@bp.post("/trips/start")
@login_required
def start_trip():
    """Сохранить начальную точку и время активной поездки."""

    origin_name = request.form.get("origin", "").strip()
    if len(origin_name) > current_app.config["MAX_TEXT_LENGTH"]:
        flash("Название места слишком длинное", "error")
        return redirect(url_for("main.index"))
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
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Поездка уже была начата в другом окне", "warning")
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
    if not destination_name:
        flash("Укажите конечную точку", "error")
        return redirect(url_for("main.index"))
    if len(destination_name) > current_app.config["MAX_TEXT_LENGTH"]:
        flash("Название места слишком длинное", "error")
        return redirect(url_for("main.index"))
    if transport_type not in TRANSPORT_LABELS:
        flash("Выберите тип перемещения", "error")
        return redirect(url_for("main.index"))
    if arrived_at <= active_trip.departed_at:
        flash("Прибытие должно быть позже отправления", "error")
        return redirect(url_for("main.index"))

    destination = get_or_create_place(g.user.id, destination_name)
    detail = request.form.get("transport_detail", "").strip() or None
    if detail and len(detail) > current_app.config["MAX_TEXT_LENGTH"]:
        flash("Описание транспорта слишком длинное", "error")
        return redirect(url_for("main.index"))
    if transport_type == "other" and detail is None:
        flash("Укажите вид перемещения", "error")
        return redirect(url_for("main.index"))
    cost = None
    taxi_tariff = None
    if transport_type in {"taxi", "ebike", "scooter"}:
        cost_value = request.form.get("cost", "").strip()
        if not cost_value and transport_type in {"ebike", "scooter"}:
            cost_value = "0"
        try:
            cost = float(cost_value) if cost_value else None
        except ValueError:
            flash("Стоимость должна быть числом", "error")
            return redirect(url_for("main.index"))
        if cost is not None and (not isfinite(cost) or cost < 0):
            flash("Стоимость должна быть конечным неотрицательным числом", "error")
            return redirect(url_for("main.index"))
    if transport_type == "taxi":
        taxi_tariff = request.form.get("taxi_tariff", "").strip() or None
        if taxi_tariff not in TAXI_TARIFFS:
            flash("Выберите тариф такси", "error")
            return redirect(url_for("main.index"))

    trip = Trip(
        user_id=g.user.id,
        origin_id=active_trip.origin_id,
        destination_id=destination.id,
        departed_at=active_trip.departed_at,
        arrived_at=arrived_at,
        transport_type=transport_type,
        transport_detail=(
            detail if transport_type in {"bus", "metro", "other"} else None
        ),
        cost=cost,
        taxi_cost=None,
        taxi_tariff=taxi_tariff,
    )
    db.session.add(trip)
    db.session.delete(active_trip)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(
            "Не удалось сохранить поездку. Обновите страницу и попробуйте ещё раз.",
            "error",
        )
        return redirect(url_for("main.index"))
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
    return redirect(url_for("main.index"))


@bp.get("/calculate")
@login_required
def calculate():
    """Показать конструктор составного маршрута."""

    return render_template("calculate.html")


@bp.get("/calculate/result")
@limiter.limit("30 per minute")
@login_required
def calculate_result():
    """Показать отдельный экран рассчитанного составного маршрута."""

    points = [
        point.strip() for point in request.args.getlist("points") if point.strip()
    ]
    if len(points) < 2:
        flash("Добавьте минимум две точки", "error")
        return redirect(url_for("main.calculate"))
    if len(points) > current_app.config["MAX_ROUTE_POINTS"]:
        flash("В маршруте слишком много точек", "error")
        return redirect(url_for("main.calculate"))
    if any(len(point) > current_app.config["MAX_TEXT_LENGTH"] for point in points):
        flash("Название точки слишком длинное", "error")
        return redirect(url_for("main.calculate"))
    return render_template(
        "calculate_result.html",
        result=calculate_route(g.user.id, points),
    )


@bp.get("/trips")
@login_required
def trips():
    """Показать полную историю поездок пользователя."""

    trip_items = db.session.scalars(
        select(Trip).where(Trip.user_id == g.user.id).order_by(Trip.departed_at.desc())
    ).all()
    return render_template(
        "trips.html", trips=trip_items, transport_labels=TRANSPORT_LABELS
    )


@bp.post("/trips/<int:trip_id>/delete")
@login_required
def delete_trip(trip_id: int):
    """Безвозвратно удалить одну принадлежащую пользователю поездку."""

    trip = db.session.scalar(
        select(Trip).where(Trip.id == trip_id, Trip.user_id == g.user.id)
    )
    if trip is None:
        return render_template(
            "error.html", code=404, message="Поездка не найдена"
        ), 404
    db.session.delete(trip)
    db.session.commit()
    flash("Поездка удалена", "success")
    return redirect(url_for("main.trips"))


@bp.post("/trips/delete-all")
@login_required
def delete_all_trips():
    """Безвозвратно удалить всю завершённую историю пользователя."""

    if request.form.get("confirm_delete") != "1":
        flash("Подтвердите удаление поездок", "warning")
        return redirect(url_for("main.trips"))
    deleted_count = db.session.scalar(
        select(db.func.count(Trip.id)).where(Trip.user_id == g.user.id)
    )
    db.session.execute(delete(Trip).where(Trip.user_id == g.user.id))
    db.session.commit()
    flash(f"История удалена · {deleted_count or 0} поездок", "success")
    return redirect(url_for("main.trips"))


@bp.get("/places")
@login_required
def places():
    """Показать сохранённые места пользователя."""

    place_items = db.session.scalars(
        select(Place).where(Place.user_id == g.user.id).order_by(Place.name)
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
    if len(name) > current_app.config["MAX_TEXT_LENGTH"]:
        flash("Название места слишком длинное", "error")
        return redirect(url_for("main.places"))
    place = get_or_create_place(g.user.id, name)
    if not _update_place_fields(place):
        db.session.rollback()
        return redirect(url_for("main.places"))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Место с таким названием уже существует", "warning")
        return redirect(url_for("main.places"))
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
    if len(name) > current_app.config["MAX_TEXT_LENGTH"]:
        flash("Название места слишком длинное", "error")
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
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Место с таким названием уже существует", "warning")
        return redirect(url_for("main.places"))
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
    trips = db.session.scalars(select(Trip).where(Trip.user_id == g.user.id)).all()
    mapped_ids = {place.id for place in places}
    map_data = {
        "places": [
            {
                "id": place.id,
                "name": place.name,
                "description": place.description,
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

    trip_items = db.session.scalars(select(Trip).where(Trip.user_id == g.user.id)).all()
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
    return render_template(
        "profile.html", stats=stats, timezone_choices=TIMEZONE_CHOICES
    )


@bp.post("/profile/timezone")
@login_required
def update_timezone():
    """Сохранить выбранный пользователем часовой пояс."""

    timezone = request.form.get("timezone", "").strip()
    if not _is_valid_timezone(timezone):
        flash("Выберите корректный часовой пояс", "error")
        return redirect(url_for("main.profile", _anchor="settings"))
    g.user.timezone = timezone
    db.session.commit()
    flash("Часовой пояс сохранён", "success")
    return redirect(url_for("main.profile", _anchor="settings"))


@bp.post("/api/timezone")
@login_required
def detect_timezone():
    """Сохранить автоматически определённый пояс, если ручного выбора ещё нет."""

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Ожидается JSON-объект"}), 400
    timezone = str(payload.get("timezone", "")).strip()
    if not _is_valid_timezone(timezone):
        return jsonify({"error": "Некорректный часовой пояс"}), 400
    if g.user.timezone is None:
        g.user.timezone = timezone
        db.session.commit()
    return "", 204


def _is_valid_timezone(value: str) -> bool:
    """Проверить идентификатор часового пояса IANA."""

    if not value or len(value) > 64:
        return False
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        return False
    return True


def _update_place_fields(place: Place) -> bool:
    """Проверить форму и записать метаданные места."""

    description = request.form.get("description", "").strip() or None
    if description and len(description) > current_app.config["MAX_TEXT_LENGTH"]:
        flash("Описание места слишком длинное", "error")
        return False
    place.description = description
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
    if parsed_latitude is not None and (
        not isfinite(parsed_latitude) or not -90 <= parsed_latitude <= 90
    ):
        flash("Широта должна быть от −90 до 90", "error")
        return False
    if parsed_longitude is not None and (
        not isfinite(parsed_longitude) or not -180 <= parsed_longitude <= 180
    ):
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
    if len(query) > current_app.config["MAX_TEXT_LENGTH"]:
        return jsonify({"error": "Запрос слишком длинный"}), 400
    statement = select(Place).where(Place.user_id == g.user.id)
    if query:
        statement = statement.where(
            Place.normalized_name.contains(normalize_place(query), autoescape=True)
        )
    places = db.session.scalars(statement.order_by(Place.name).limit(8)).all()
    return jsonify([{"id": place.id, "name": place.name} for place in places])


@bp.get("/api/metro-lines")
@login_required
def metro_lines_api():
    """Вернуть сохранённые пользователем названия веток метро."""

    raw_query = request.args.get("q", "")
    if len(raw_query) > current_app.config["MAX_TEXT_LENGTH"]:
        return jsonify({"error": "Запрос слишком длинный"}), 400
    query = normalize_place(raw_query)
    values = db.session.scalars(
        select(Trip.transport_detail).where(
            Trip.user_id == g.user.id,
            Trip.transport_type == "metro",
            Trip.transport_detail.is_not(None),
        )
    ).all()
    unique_lines: dict[str, str] = {}
    for value in values:
        if value:
            unique_lines.setdefault(normalize_place(value), value)
    matches = [
        name
        for normalized, name in unique_lines.items()
        if not query or query in normalized
    ]
    matches.sort(key=normalize_place)
    return jsonify([{"name": name} for name in matches[:8]])


@bp.post("/api/calculate")
@limiter.limit("30 per minute")
@login_required
def calculate_api():
    """Вернуть оценку времени для последовательности точек."""

    payload = request.get_json(silent=True) or {}
    raw_points = payload.get("points", []) if isinstance(payload, dict) else []
    if not isinstance(raw_points, list) or any(
        not isinstance(point, str) for point in raw_points
    ):
        return jsonify({"error": "Точки должны быть списком строк"}), 400
    points = [point.strip() for point in raw_points if point.strip()]
    if len(points) < 2:
        return jsonify({"error": "Добавьте минимум две точки"}), 400
    if len(points) > current_app.config["MAX_ROUTE_POINTS"]:
        return jsonify({"error": "В маршруте слишком много точек"}), 400
    if any(len(point) > current_app.config["MAX_TEXT_LENGTH"] for point in points):
        return jsonify({"error": "Название точки слишком длинное"}), 400
    return jsonify(calculate_route(g.user.id, points))
