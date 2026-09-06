"""Небольшие совместимые миграции локальной SQLite-базы."""

from sqlalchemy import text

from app.extensions import db


def upgrade_sqlite_schema() -> None:
    """Добавить новые поля мест в ранее созданную базу без потери данных."""

    columns = {
        row[1]
        for row in db.session.execute(text("PRAGMA table_info(place)")).all()
    }
    additions = {
        "address": "ALTER TABLE place ADD COLUMN address VARCHAR",
        "latitude": "ALTER TABLE place ADD COLUMN latitude FLOAT",
        "longitude": "ALTER TABLE place ADD COLUMN longitude FLOAT",
        "description": "ALTER TABLE place ADD COLUMN description VARCHAR",
        "marker_color": (
            "ALTER TABLE place ADD COLUMN marker_color VARCHAR "
            "NOT NULL DEFAULT '#111111'"
        ),
    }
    for name, statement in additions.items():
        if name not in columns:
            db.session.execute(text(statement))
    db.session.commit()
