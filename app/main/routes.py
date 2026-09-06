"""Страницы, JSON API и сохранение поездок."""

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


@bp.get("/")
def index():
    """Показать форму записи поездки."""

    recent_trips = []
    active_trip = None
    if g.user:
        active_trip = db.session.scalar(
            select(ActiveTrip).where(ActiveTrip.user_id == g.user.id)
        )
        recent_trips = db.session.scalars(
            select(Trip)
            .where(Trip.user_id == g.user.id)
            .order_by(Trip.departed_at.desc())
            .limit(5)
        ).all()
    return render_template(
        "index.html",
        active_trip=active_trip,
        recent_trips=recent_trips,
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
