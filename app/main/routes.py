"""Страницы, JSON API и сохранение поездок."""

import json
import re
import secrets
from collections import Counter
from math import isfinite
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import (
    current_app,
    flash,
    g,
    get_flashed_messages,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.auth.helpers import login_required
from app.extensions import db, limiter
from app.main import bp
from app.models import ActiveTrip, Place, SavedRoute, Trip, utc_now
from app.services import (
    TAXI_TARIFFS,
    TIMEZONE_CHOICES,
    TRANSPORT_LABELS,
    calculate_route,
    calculate_route_variants,
    get_or_create_place,
    normalize_place,
    parse_local_datetime,
)

COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
SHARE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32}$")
MAX_SAVED_ROUTES = 50


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


@bp.get("/manifest.webmanifest")
def webmanifest():
    """Отдать PWA manifest с корневой областью приложения."""

    response = current_app.send_static_file("manifest.webmanifest")
    response.mimetype = "application/manifest+json"
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@bp.get("/service-worker.js")
def service_worker():
    """Отдать service worker из корня, чтобы его scope охватывал приложение."""

    response = current_app.send_static_file("service-worker.js")
    response.mimetype = "application/javascript"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@bp.get("/legal-update")
@login_required
def legal_update():
    """Показать новую редакцию документов до продолжения работы."""

    return render_template("legal_update.html")


@bp.post("/legal-update/accept")
@login_required
def accept_legal_update():
    """Зафиксировать явное принятие новой версии соглашения."""

    g.user.terms_version = current_app.config["LEGAL_DOCUMENT_VERSION"]
    g.user.terms_accepted_at = utc_now()
    db.session.commit()
    return redirect(url_for("main.index"))


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
    """Показать найденные по истории варианты маршрута между двумя местами."""

    legacy_points = [
        point.strip() for point in request.args.getlist("points") if point.strip()
    ]
    origin = request.args.get("origin", "").strip()
    destination = request.args.get("destination", "").strip()
    if not origin and len(legacy_points) == 2:
        origin, destination = legacy_points
    if not origin or not destination:
        flash("Укажите начальную и конечную точки", "error")
        return redirect(url_for("main.calculate"))
    if any(
        len(point) > current_app.config["MAX_TEXT_LENGTH"]
        for point in (origin, destination)
    ):
        flash("Название точки слишком длинное", "error")
        return redirect(url_for("main.calculate"))
    return render_template(
        "calculate_result.html",
        route_search=calculate_route_variants(
            g.user.id,
            origin,
            destination,
            max_intermediate_points=current_app.config["MAX_ROUTE_INTERMEDIATE_POINTS"],
            max_variants=current_app.config["MAX_ROUTE_VARIANTS"],
        ),
    )


@bp.post("/routes")
@limiter.limit("30 per minute")
@login_required
def save_route():
    """Сохранить проверенный снимок выбранного варианта маршрута."""

    title = " ".join(request.form.get("title", "").split())
    origin = request.form.get("origin", "").strip()
    destination = request.form.get("destination", "").strip()
    variant_index = request.form.get("variant_index", type=int)
    result_url = url_for(
        "main.calculate_result", origin=origin, destination=destination
    )
    max_length = current_app.config["MAX_TEXT_LENGTH"]
    if not title:
        flash("Введите название маршрута", "error")
        return redirect(result_url)
    if any(len(value) > max_length for value in (title, origin, destination)):
        flash("Название маршрута или точки слишком длинное", "error")
        return redirect(result_url)
    if not origin or not destination or variant_index is None or variant_index < 0:
        flash("Не удалось определить вариант маршрута", "error")
        return redirect(result_url)
    saved_count = db.session.scalar(
        select(db.func.count(SavedRoute.id)).where(SavedRoute.user_id == g.user.id)
    )
    if (saved_count or 0) >= MAX_SAVED_ROUTES:
        flash("Можно сохранить не больше 50 маршрутов", "warning")
        return redirect(result_url)
    route_search = calculate_route_variants(
        g.user.id,
        origin,
        destination,
        max_intermediate_points=current_app.config["MAX_ROUTE_INTERMEDIATE_POINTS"],
        max_variants=current_app.config["MAX_ROUTE_VARIANTS"],
    )
    if variant_index >= len(route_search["variants"]):
        flash("Этот вариант маршрута больше недоступен", "error")
        return redirect(result_url)
    snapshot = _shareable_route_snapshot(route_search["variants"][variant_index])
    saved_route = SavedRoute(
        user_id=g.user.id,
        title=title,
        origin_name=route_search["origin"],
        destination_name=route_search["destination"],
        route_data=json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
        public_token=_new_share_token(),
    )
    db.session.add(saved_route)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        current_app.logger.warning("Не удалось создать уникальную ссылку маршрута")
        flash("Не удалось сохранить маршрут. Попробуйте ещё раз.", "error")
        return redirect(result_url)
    flash("Маршрут сохранён в профиле", "success")
    return redirect(url_for("main.profile", _anchor="saved-routes"))


@bp.get("/r/<token>")
@limiter.limit("60 per minute")
def shared_route(token: str):
    """Показать обезличенную карточку маршрута по публичной ссылке."""

    if not SHARE_TOKEN_PATTERN.fullmatch(token):
        return render_template("error.html", code=404, message="Маршрут не найден"), 404
    saved_route = db.session.scalar(
        select(SavedRoute).where(SavedRoute.public_token == token)
    )
    route = _load_saved_route(saved_route) if saved_route else None
    if saved_route is None or route is None:
        return render_template("error.html", code=404, message="Маршрут не найден"), 404
    response = make_response(
        render_template(
            "shared_route.html",
            saved_route=_saved_route_view(saved_route, route),
        )
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@bp.post("/routes/<int:saved_route_id>/delete")
@login_required
def delete_saved_route(saved_route_id: int):
    """Удалить карточку пользователя и отозвать её публичную ссылку."""

    saved_route = db.session.scalar(
        select(SavedRoute).where(
            SavedRoute.id == saved_route_id,
            SavedRoute.user_id == g.user.id,
        )
    )
    if saved_route is None:
        return render_template("error.html", code=404, message="Маршрут не найден"), 404
    db.session.delete(saved_route)
    db.session.commit()
    flash("Маршрут удалён, публичная ссылка отозвана", "success")
    return redirect(url_for("main.profile", _anchor="saved-routes"))


def _filtered_trips(query):
    statement = select(Trip).where(Trip.user_id == g.user.id)
    for word in normalize_place(query).split():
        statement = statement.where(
            or_(
                Trip.origin.has(Place.normalized_name.contains(word, autoescape=True)),
                Trip.destination.has(
                    Place.normalized_name.contains(word, autoescape=True)
                ),
            )
        )
    return db.session.scalars(
        statement.order_by(Trip.departed_at.desc(), Trip.id.desc())
    ).all()


@bp.get("/trips")
@login_required
def trips():
    """История с поиском по названиям начального и конечного места."""
    query = request.args.get("q", "").strip()
    if len(query) > current_app.config["MAX_TEXT_LENGTH"]:
        flash("Запрос слишком длинный", "error")
        return redirect(url_for("main.trips"))
    # Project only the fields used by the history; avoid loading ORM relations.
    origin = aliased(Place)
    destination = aliased(Place)
    limit = 10_000
    page_size = 50
    rows = db.session.execute(
        select(
            Trip.id,
            origin.name,
            destination.name,
            Trip.transport_type,
            Trip.departed_at,
            Trip.arrived_at,
        )
        .join(origin, Trip.origin_id == origin.id)
        .join(destination, Trip.destination_id == destination.id)
        .where(Trip.user_id == g.user.id)
        .order_by(Trip.departed_at.desc(), Trip.id.desc())
        .limit(limit + 1)
    ).all()
    history = [
        {
            "id": row[0],
            "origin": row[1],
            "destination": row[2],
            "transport": TRANSPORT_LABELS.get(row[3], "Другое"),
            "minutes": round((row[5] - row[4]).total_seconds() / 60),
        }
        for row in rows[:limit]
    ]
    words = normalize_place(query).split()
    matches = [
        trip
        for trip in history
        if all(
            word in normalize_place(trip["origin"])
            or word in normalize_place(trip["destination"])
            for word in words
        )
    ]
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    page_count = max(1, (len(matches) + page_size - 1) // page_size)
    page = min(page, page_count)
    return render_template(
        "trips.html",
        history=history,
        visible_trips=matches[(page - 1) * page_size : page * page_size],
        match_count=len(matches),
        query=query,
        page=page,
        page_count=page_count,
        history_limited=len(rows) > limit,
        history_limit=limit,
        page_size=page_size,
    )


@bp.get("/trips/manage")
@login_required
def manage_trips():
    query = request.args.get("q", "").strip()
    if len(query) > current_app.config["MAX_TEXT_LENGTH"]:
        flash("Запрос слишком длинный", "error")
        return redirect(url_for("main.manage_trips"))
    return render_template(
        "manage_trips.html",
        trips=_filtered_trips(query),
        transport_labels=TRANSPORT_LABELS,
        taxi_tariffs=TAXI_TARIFFS,
        query=query,
    )


@bp.get("/trips/<int:trip_id>")
@login_required
def trip_detail(trip_id: int):
    trip = db.session.scalar(
        select(Trip).where(Trip.id == trip_id, Trip.user_id == g.user.id)
    )
    if trip is None:
        return render_template(
            "error.html", code=404, message="Поездка не найдена"
        ), 404
    return render_template(
        "trip_detail.html",
        trip=trip,
        transport_labels=TRANSPORT_LABELS,
        taxi_tariffs=TAXI_TARIFFS,
        trip_detail=True,
    )


@bp.get("/trips/<int:trip_id>/edit")
@login_required
def trip_edit_page(trip_id: int):
    trip = db.session.scalar(
        select(Trip).where(Trip.id == trip_id, Trip.user_id == g.user.id)
    )
    if trip is None:
        return render_template(
            "error.html", code=404, message="Поездка не найдена"
        ), 404
    return render_template(
        "trip_edit.html",
        trip=trip,
        transport_labels=TRANSPORT_LABELS,
        taxi_tariffs=TAXI_TARIFFS,
        trip_detail=True,
        edit_page=True,
    )


@bp.post("/trips/<int:trip_id>/edit")
@login_required
def edit_trip(trip_id: int):
    trip = db.session.scalar(
        select(Trip).where(Trip.id == trip_id, Trip.user_id == g.user.id)
    )
    if trip is None:
        return render_template(
            "error.html", code=404, message="Поездка не найдена"
        ), 404
    try:
        origin = request.form.get("origin", "").strip()
        destination = request.form.get("destination", "").strip()
        detail = request.form.get("transport_detail", "").strip() or None
        if not origin or not destination:
            raise ValueError("Укажите начальное и конечное место")
        if any(
            len(value) > current_app.config["MAX_TEXT_LENGTH"]
            for value in (origin, destination, detail or "")
        ):
            raise ValueError("Название или описание слишком длинное")
        try:
            departed_at = parse_local_datetime(request.form.get("departed_at", ""))
            arrived_at = parse_local_datetime(request.form.get("arrived_at", ""))
        except ValueError:
            raise ValueError("Проверьте время отправления и прибытия") from None
        if arrived_at <= departed_at:
            raise ValueError("Прибытие должно быть позже отправления")
        transport = request.form.get("transport_type", "")
        if transport not in TRANSPORT_LABELS:
            raise ValueError("Выберите тип перемещения")
        if transport == "other" and not detail:
            raise ValueError("Укажите вид перемещения")
        cost_value = request.form.get("cost", "").strip()
        try:
            cost = float(cost_value) if cost_value else None
        except ValueError:
            raise ValueError("Стоимость должна быть числом") from None
        if cost is not None and (not isfinite(cost) or cost < 0):
            raise ValueError("Стоимость должна быть конечным неотрицательным числом")
        tariff = request.form.get("taxi_tariff", "").strip() or None
        if transport == "taxi" and tariff not in TAXI_TARIFFS:
            raise ValueError("Выберите тариф такси")
    except ValueError as error:
        flash(str(error) or "Проверьте данные поездки", "error")
        if request.form.get("edit_page") == "1":
            return render_template(
                "trip_edit.html",
                trip=trip,
                transport_labels=TRANSPORT_LABELS,
                taxi_tariffs=TAXI_TARIFFS,
                trip_detail=True,
                edit_page=True,
                edit_values=request.form,
            ), 400
        return redirect(
            url_for("main.trip_detail", trip_id=trip_id)
            if request.form.get("return_to") == "trip"
            else url_for("main.manage_trips", _anchor=f"trip-{trip_id}")
        )
    trip.origin = get_or_create_place(g.user.id, origin)
    trip.destination = get_or_create_place(g.user.id, destination)
    trip.departed_at = departed_at
    trip.arrived_at = arrived_at
    trip.transport_type = transport
    trip.transport_detail = detail if transport in {"bus", "metro", "other"} else None
    trip.cost = cost if transport in {"taxi", "ebike", "scooter"} else None
    trip.taxi_cost = None
    trip.taxi_tariff = tariff if transport == "taxi" else None
    db.session.commit()
    flash("Поездка изменена", "success")
    return redirect(
        url_for("main.trip_detail", trip_id=trip_id)
        if request.form.get("return_to") == "trip"
        else url_for("main.manage_trips", _anchor=f"trip-{trip_id}")
    )


@bp.post("/trips/<int:trip_id>/delete")
@login_required
def delete_trip(trip_id: int):
    """Удалить одну принадлежащую пользователю поездку из активной базы."""

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
    return redirect(
        url_for(
            "main.trips"
            if request.form.get("return_to") == "trip"
            else "main.manage_trips"
        )
    )


@bp.post("/trips/delete-all")
@login_required
def delete_all_trips():
    """Удалить завершённую историю пользователя из активной базы."""

    if request.form.get("confirm_delete") != "1":
        flash("Подтвердите удаление поездок", "warning")
        return redirect(url_for("main.profile", _anchor="settings"))
    deleted_count = db.session.scalar(
        select(db.func.count(Trip.id)).where(Trip.user_id == g.user.id)
    )
    db.session.execute(delete(Trip).where(Trip.user_id == g.user.id))
    db.session.commit()
    flash(f"История удалена · {deleted_count or 0} поездок", "success")
    return redirect(url_for("main.profile", _anchor="settings"))


@bp.get("/places")
@login_required
def places():
    """Показать сохранённые места пользователя с поиском."""

    query = request.args.get("q", "").strip()
    if len(query) > current_app.config["MAX_TEXT_LENGTH"]:
        flash("Запрос слишком длинный", "error")
        return redirect(url_for("main.places"))
    statement = select(Place).where(Place.user_id == g.user.id)
    if query:
        statement = statement.where(
            Place.normalized_name.contains(normalize_place(query), autoescape=True)
        )
    place_items = db.session.scalars(statement.order_by(Place.name)).all()
    return render_template("places.html", places=place_items, query=query)


@bp.get("/places/<int:place_id>/edit")
@login_required
def place_edit_page(place_id):
    """Открыть редактор принадлежащего пользователю места."""
    place = db.session.scalar(
        select(Place).where(Place.id == place_id, Place.user_id == g.user.id)
    )
    if place is None:
        return render_template("error.html", code=404, message="Место не найдено"), 404
    targets = db.session.scalars(
        select(Place)
        .where(Place.user_id == g.user.id, Place.id != place.id)
        .order_by(Place.name)
    ).all()
    return render_template("place_edit.html", place=place, merge_targets=targets)


def _place_response(return_url, place=None):
    if request.accept_mimetypes.best != "application/json":
        return redirect(return_url)
    if place is None:
        messages = get_flashed_messages()
        return jsonify(
            error=messages[-1] if messages else "Не удалось сохранить место"
        ), 400
    return jsonify(
        place={
            "id": place.id,
            "name": place.name,
            "description": place.description or "",
            "lat": place.latitude,
            "lng": place.longitude,
            "color": place.marker_color,
            "updateUrl": url_for("main.update_place", place_id=place.id),
        }
    )


@bp.post("/places/<int:place_id>/delete")
@login_required
def delete_place(place_id):
    """Удалить своё место; связанные поездки — только при явном выборе."""
    place = db.session.scalar(
        select(Place).where(Place.id == place_id, Place.user_id == g.user.id)
    )
    if place is None:
        return render_template("error.html", code=404, message="Место не найдено"), 404
    trip_filter = (Trip.user_id == g.user.id) & or_(
        Trip.origin_id == place.id, Trip.destination_id == place.id
    )
    active_filter = (ActiveTrip.user_id == g.user.id) & (
        ActiveTrip.origin_id == place.id
    )
    has_trips = (
        db.session.scalar(select(Trip.id).where(trip_filter).limit(1)) is not None
    )
    has_active = (
        db.session.scalar(select(ActiveTrip.id).where(active_filter).limit(1))
        is not None
    )
    if (has_trips or has_active) and request.form.get("delete_related") != "1":
        flash(
            "У места есть поездки. Объедините его с другим местом, чтобы сохранить историю, или отметьте удаление связанных поездок.",
            "error",
        )
        return redirect(url_for("main.places"))
    db.session.execute(delete(Trip).where(trip_filter))
    db.session.execute(delete(ActiveTrip).where(active_filter))
    db.session.delete(place)
    db.session.commit()
    flash("Место удалено", "success")
    return redirect(url_for("main.places"))


@bp.post("/places/<int:place_id>/merge")
@login_required
def merge_place(place_id):
    source = db.session.scalar(
        select(Place).where(Place.id == place_id, Place.user_id == g.user.id)
    )
    target_id = request.form.get("target_id", type=int)
    target = db.session.scalar(
        select(Place).where(Place.id == target_id, Place.user_id == g.user.id)
    )
    if source is None or target is None or source.id == target.id:
        flash("Выберите другое своё место для объединения", "error")
        return redirect(url_for("main.places"))
    for model, field in (
        (Trip, "origin_id"),
        (Trip, "destination_id"),
        (ActiveTrip, "origin_id"),
    ):
        db.session.execute(
            update(model)
            .where(model.user_id == g.user.id, getattr(model, field) == source.id)
            .values({field: target.id})
        )
    db.session.delete(source)
    db.session.commit()
    flash(f"Места объединены в «{target.name}» · поездки сохранены", "success")
    return redirect(url_for("main.places"))


@bp.post("/places")
@login_required
def create_place():
    """Создать место и сохранить его дополнительные данные."""

    return_url = (
        url_for("main.map_view")
        if request.form.get("return_to") == "map"
        else url_for("main.places")
    )
    name = request.form.get("name", "").strip()
    if not name:
        flash("Введите название места", "error")
        return _place_response(return_url)
    if len(name) > current_app.config["MAX_TEXT_LENGTH"]:
        flash("Название места слишком длинное", "error")
        return _place_response(return_url)
    place = get_or_create_place(g.user.id, name)
    if not _update_place_fields(place):
        db.session.rollback()
        return _place_response(return_url)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Место с таким названием уже существует", "warning")
        return _place_response(return_url)
    if request.accept_mimetypes.best == "application/json":
        return _place_response(return_url, place)
    if request.form.get("choose_on_map") == "1":
        flash("Место сохранено · выберите положение на карте", "success")
        return redirect(url_for("main.map_view", pick=place.id))
    flash("Место сохранено", "success")
    return _place_response(return_url)


@bp.post("/places/<int:place_id>")
@login_required
def update_place(place_id: int):
    """Обновить принадлежащее пользователю место."""

    place = db.session.scalar(
        select(Place).where(Place.id == place_id, Place.user_id == g.user.id)
    )
    if place is None:
        return render_template("error.html", code=404, message="Место не найдено"), 404
    choose_on_map = request.form.get("choose_on_map") == "1"
    return_url = (
        url_for("main.map_view")
        if request.form.get("return_to") == "map"
        else url_for("main.place_edit_page", place_id=place.id)
        if request.form.get("return_to") == "edit"
        else url_for("main.places")
    )
    name = request.form.get("name", "").strip()
    if not name:
        flash("Название не может быть пустым", "error")
        return _place_response(return_url)
    if len(name) > current_app.config["MAX_TEXT_LENGTH"]:
        flash("Название места слишком длинное", "error")
        return _place_response(return_url)
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
        return _place_response(return_url)
    place.name = " ".join(name.split())
    place.normalized_name = normalized
    if not _update_place_fields(place):
        db.session.rollback()
        return _place_response(return_url)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Место с таким названием уже существует", "warning")
        return _place_response(return_url)
    if request.accept_mimetypes.best == "application/json":
        return _place_response(return_url, place)
    if choose_on_map:
        flash("Данные сохранены · выберите положение на карте", "success")
        return redirect(url_for("main.map_view", pick=place.id))
    flash("Изменения сохранены", "success")
    return _place_response(return_url)


@bp.get("/map")
@login_required
def map_view():
    """Показать места и поездки с координатами на карте."""

    all_places = db.session.scalars(
        select(Place).where(Place.user_id == g.user.id).order_by(Place.name)
    ).all()
    places = [
        place
        for place in all_places
        if place.latitude is not None and place.longitude is not None
    ]
    unmapped_places = [
        place
        for place in all_places
        if place.latitude is None or place.longitude is None
    ]
    requested_pick_id = request.args.get("pick", type=int)
    pick_place_id = (
        requested_pick_id
        if requested_pick_id in {place.id for place in all_places}
        else None
    )
    trips = db.session.scalars(select(Trip).where(Trip.user_id == g.user.id)).all()
    mapped_ids = {place.id for place in places}
    map_data = {
        "createUrl": url_for("main.create_place"),
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
        "placeEditors": [
            {
                "id": place.id,
                "name": place.name,
                "description": place.description or "",
                "lat": place.latitude,
                "lng": place.longitude,
                "color": place.marker_color,
                "updateUrl": url_for("main.update_place", place_id=place.id),
            }
            for place in all_places
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
    return render_template(
        "map.html",
        map_data=map_data,
        pick_place_id=pick_place_id,
        places=places,
        unmapped_places=unmapped_places,
    )


@bp.get("/profile")
@login_required
def profile():
    """Показать профиль Яндекса и личную статистику поездок."""

    trip_items = db.session.scalars(
        select(Trip).where(Trip.user_id == g.user.id).order_by(Trip.departed_at.desc())
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
    saved_route_models = db.session.scalars(
        select(SavedRoute)
        .where(SavedRoute.user_id == g.user.id)
        .order_by(SavedRoute.created_at.desc())
        .limit(MAX_SAVED_ROUTES)
    ).all()
    saved_routes = [
        _saved_route_view(saved_route, route)
        for saved_route in saved_route_models
        if (route := _load_saved_route(saved_route)) is not None
    ]
    return render_template(
        "profile.html",
        stats=stats,
        saved_routes=saved_routes,
        timezone_choices=TIMEZONE_CHOICES,
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


def _shareable_route_snapshot(route: dict) -> dict:
    """Удалить внутренние идентификаторы и координаты из публичного снимка."""

    segment_fields = (
        "from",
        "to",
        "known",
        "minutes",
        "min_minutes",
        "max_minutes",
        "samples",
        "transport",
        "transport_detail",
        "distance_km",
        "speed_kmh",
    )
    return {
        "points": [{"name": point["name"]} for point in route["points"]],
        "segments": [
            {field: segment.get(field) for field in segment_fields}
            for segment in route["segments"]
        ],
        "total_minutes": route["total_minutes"],
        "total_distance_km": route["total_distance_km"],
        "average_speed_kmh": route["average_speed_kmh"],
        "observations": route["observations"],
    }


def _new_share_token() -> str:
    """Создать непредсказуемый токен, отсутствующий в текущей базе."""

    while True:
        token = secrets.token_urlsafe(24)
        exists = db.session.scalar(
            select(SavedRoute.id).where(SavedRoute.public_token == token)
        )
        if exists is None:
            return token


def _load_saved_route(saved_route: SavedRoute) -> dict | None:
    """Безопасно прочитать сохранённый сервером снимок маршрута."""

    try:
        route = json.loads(saved_route.route_data)
    except (json.JSONDecodeError, TypeError):
        return None
    required = {
        "points",
        "segments",
        "total_minutes",
        "total_distance_km",
        "average_speed_kmh",
        "observations",
    }
    if not isinstance(route, dict) or not required.issubset(route):
        return None
    if not isinstance(route["points"], list) or not isinstance(route["segments"], list):
        return None
    return route


def _saved_route_view(saved_route: SavedRoute, route: dict) -> dict:
    """Подготовить карточку и её минимальные данные для клиентского шаринга."""

    share_url = url_for(
        "main.shared_route", token=saved_route.public_token, _external=True
    )
    share_payload = {
        "title": saved_route.title,
        "origin": saved_route.origin_name,
        "destination": saved_route.destination_name,
        "route": route,
        "shareUrl": share_url,
    }
    return {
        "id": saved_route.id,
        "title": saved_route.title,
        "origin": saved_route.origin_name,
        "destination": saved_route.destination_name,
        "route": route,
        "created_at": saved_route.created_at,
        "share_url": share_url,
        "share_payload": share_payload,
    }


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
    if isinstance(payload, dict) and ("origin" in payload or "destination" in payload):
        origin = payload.get("origin")
        destination = payload.get("destination")
        if not isinstance(origin, str) or not isinstance(destination, str):
            return jsonify({"error": "Точки должны быть строками"}), 400
        origin, destination = origin.strip(), destination.strip()
        if not origin or not destination:
            return jsonify({"error": "Укажите начальную и конечную точки"}), 400
        if any(
            len(point) > current_app.config["MAX_TEXT_LENGTH"]
            for point in (origin, destination)
        ):
            return jsonify({"error": "Название точки слишком длинное"}), 400
        return jsonify(
            calculate_route_variants(
                g.user.id,
                origin,
                destination,
                max_intermediate_points=current_app.config[
                    "MAX_ROUTE_INTERMEDIATE_POINTS"
                ],
                max_variants=current_app.config["MAX_ROUTE_VARIANTS"],
            )
        )
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
