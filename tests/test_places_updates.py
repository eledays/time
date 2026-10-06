from datetime import UTC, datetime, timedelta

from app.extensions import db
from app.models import ActiveTrip, Place, Trip, User


def test_map_save_json_and_validation(auth_client, app, user):
    response = auth_client.post(
        "/places",
        data={
            "csrf_token": "test-csrf",
            "name": "Точка",
            "latitude": "55",
            "longitude": "37",
            "return_to": "map",
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    place = response.json["place"]
    assert place["lat"] == 55
    response = auth_client.post(
        place["updateUrl"],
        data={
            "csrf_token": "test-csrf",
            "name": "Новое имя",
            "latitude": "100",
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 400
    assert "error" in response.json
    with app.app_context():
        assert db.session.get(Place, place["id"]).name == "Точка"


def test_merge_moves_history_and_active_trip(auth_client, app, user):
    with app.app_context():
        source = Place(user_id=user.id, name="А", normalized_name="а")
        target = Place(
            user_id=user.id, name="Б", normalized_name="б", latitude=55, longitude=37
        )
        db.session.add_all([source, target])
        db.session.flush()
        source_id, target_id = source.id, target.id
        now = datetime.now(UTC)
        trip = Trip(
            user_id=user.id,
            origin_id=source.id,
            destination_id=source.id,
            departed_at=now,
            arrived_at=now + timedelta(minutes=10),
            transport_type="walk",
        )
        active = ActiveTrip(user_id=user.id, origin_id=source.id, departed_at=now)
        db.session.add_all([trip, active])
        db.session.commit()
    response = auth_client.post(
        f"/places/{source_id}/merge",
        data={
            "csrf_token": "test-csrf",
            "target_id": target_id,
        },
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Place, source_id) is None
        trip = db.session.scalar(db.select(Trip))
        assert trip.origin_id == trip.destination_id == target_id
        assert db.session.scalar(db.select(ActiveTrip)).origin_id == target_id
        assert db.session.get(Place, target_id).latitude == 55


def test_merge_rejects_other_users_place(auth_client, app, user):
    with app.app_context():
        other = User(yandex_id="other", display_name="Other")
        db.session.add(other)
        db.session.flush()
        source = Place(user_id=user.id, name="А", normalized_name="а")
        target = Place(user_id=other.id, name="Б", normalized_name="б")
        db.session.add_all([source, target])
        db.session.commit()
        source_id, target_id = source.id, target.id
    auth_client.post(
        f"/places/{source_id}/merge",
        data={"csrf_token": "test-csrf", "target_id": target_id},
    )
    with app.app_context():
        assert db.session.get(Place, source_id) is not None


def test_delete_unused_place(auth_client, app, user):
    with app.app_context():
        place = Place(user_id=user.id, name="Точка", normalized_name="точка")
        db.session.add(place)
        db.session.commit()
        place_id = place.id
    assert f'href="/places/{place_id}/edit"' in auth_client.get("/places").text
    assert ">Удалить</button>" in auth_client.get(f"/places/{place_id}/edit").text
    response = auth_client.post(
        f"/places/{place_id}/delete", data={"csrf_token": "test-csrf"}
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Place, place_id) is None


def test_delete_related_requires_explicit_choice(auth_client, app, user):
    with app.app_context():
        place = Place(user_id=user.id, name="А", normalized_name="а")
        other = Place(user_id=user.id, name="Б", normalized_name="б")
        db.session.add_all([place, other])
        db.session.flush()
        place_id, other_id = place.id, other.id
        now = datetime.now(UTC)
        for origin, destination in [
            (place.id, other.id),
            (other.id, place.id),
            (other.id, other.id),
        ]:
            db.session.add(
                Trip(
                    user_id=user.id,
                    origin_id=origin,
                    destination_id=destination,
                    departed_at=now,
                    arrived_at=now + timedelta(minutes=10),
                    transport_type="walk",
                )
            )
        db.session.add(ActiveTrip(user_id=user.id, origin_id=place.id, departed_at=now))
        db.session.commit()
    auth_client.post(f"/places/{place_id}/delete", data={"csrf_token": "test-csrf"})
    with app.app_context():
        assert db.session.get(Place, place_id) is not None
        assert len(db.session.scalars(db.select(Trip)).all()) == 3
        assert db.session.scalar(db.select(ActiveTrip)) is not None
    auth_client.post(
        f"/places/{place_id}/delete",
        data={"csrf_token": "test-csrf", "delete_related": "1"},
    )
    with app.app_context():
        assert db.session.get(Place, place_id) is None
        assert db.session.get(Place, other_id) is not None
        assert len(db.session.scalars(db.select(Trip)).all()) == 1
        assert db.session.scalar(db.select(ActiveTrip)) is None


def test_delete_rejects_foreign_place_and_missing_csrf(auth_client, app, user):
    with app.app_context():
        other = User(yandex_id="other-delete", display_name="Other")
        db.session.add(other)
        db.session.flush()
        place = Place(user_id=other.id, name="А", normalized_name="а")
        db.session.add(place)
        db.session.commit()
        place_id = place.id
    assert (
        auth_client.post(
            f"/places/{place_id}/delete", data={"delete_related": "1"}
        ).status_code
        == 400
    )
    assert (
        auth_client.post(
            f"/places/{place_id}/delete",
            data={"csrf_token": "test-csrf", "delete_related": "1"},
        ).status_code
        == 404
    )
    with app.app_context():
        assert db.session.get(Place, place_id) is not None


def test_separate_place_editor_and_save(auth_client, app, user):
    with app.app_context():
        place = Place(user_id=user.id, name="Дом", normalized_name="дом")
        target = Place(user_id=user.id, name="Работа", normalized_name="работа")
        db.session.add_all([place, target])
        db.session.commit()
        place_id = place.id
    listing = auth_client.get("/places").text
    assert f'href="/places/{place_id}/edit"' in listing
    assert "Объединить места" not in listing
    page = auth_client.get(f"/places/{place_id}/edit")
    assert page.status_code == 200
    assert 'class="secondary-button" type="submit" >Объединить' in page.text
    assert "<h1" not in page.text
    ordered = [
        "data-place-mini-map",
        ">Изменить место на карте",
        'id="place-name"',
        'id="place-description"',
        'id="place-color"',
        ">Сохранить</button>",
        ">Объединение</h2>",
        'id="merge-target"',
        ">Объединить</button>",
        ">Удалить</button>",
        'name="delete_related"',
    ]
    positions = [page.text.index(item) for item in ordered]
    assert positions == sorted(positions)
    assert "Поездки перенесутся в выбранное место" not in page.text
    response = auth_client.post(
        f"/places/{place_id}",
        data={"csrf_token": "test-csrf", "return_to": "edit", "name": "Новый дом"},
    )
    assert response.location.endswith(f"/places/{place_id}/edit")
    assert "Новый дом" in auth_client.get(response.location).text


def test_place_editor_ownership(auth_client, app, user):
    with app.app_context():
        other = User(yandex_id="editor-other", display_name="Other")
        db.session.add(other)
        db.session.flush()
        place = Place(user_id=other.id, name="Чужое", normalized_name="чужое")
        db.session.add(place)
        db.session.commit()
        place_id = place.id
    assert auth_client.get(f"/places/{place_id}/edit").status_code == 404
    assert auth_client.get("/places/999999/edit").status_code == 404


def test_place_mini_map_coordinates_and_empty_state(auth_client, app, user):
    with app.app_context():
        mapped = Place(
            user_id=user.id,
            name="Ноль",
            normalized_name="ноль",
            latitude=0,
            longitude=0,
            marker_color="#123456",
        )
        empty = Place(user_id=user.id, name="Без точки", normalized_name="без точки")
        db.session.add_all([mapped, empty])
        db.session.commit()
        mapped_id, empty_id = mapped.id, empty.id
    page = auth_client.get(f"/places/{mapped_id}/edit").text
    assert 'data-latitude="0.0"' in page
    assert 'data-longitude="0.0"' in page
    assert 'data-color="#123456"' in page
    assert "ol@v10.6.1/dist/ol.js" in page
    page = auth_client.get(f"/places/{empty_id}/edit").text
    assert 'data-latitude=""' in page
    assert "Положение места пока не указано" in page
