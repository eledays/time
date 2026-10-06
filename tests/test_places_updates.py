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
