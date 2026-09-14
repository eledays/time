"""Create the initial application schema and adopt known legacy SQLite databases.

Revision ID: 20260914_0001
Revises: None
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table: str) -> set[str]:
    """Return columns visible before the migration for a legacy table."""

    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Create a fresh schema or add fields used by supported legacy databases."""

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "user" not in tables:
        op.create_table(
            "user",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("yandex_id", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("email", sa.String(), nullable=True),
            sa.Column("avatar_url", sa.String(), nullable=True),
            sa.Column("timezone", sa.String(), nullable=True),
            sa.Column("terms_version", sa.String(), nullable=True),
            sa.Column("terms_accepted_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_user_yandex_id", "user", ["yandex_id"], unique=True)
    else:
        columns = _column_names("user")
        for name, column_type in (
            ("timezone", sa.String()),
            ("terms_version", sa.String()),
            ("terms_accepted_at", sa.DateTime()),
        ):
            if name not in columns:
                op.add_column("user", sa.Column(name, column_type, nullable=True))

    if "place" not in tables:
        op.create_table(
            "place",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("normalized_name", sa.String(), nullable=False),
            sa.Column("address", sa.String(), nullable=True),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column(
                "marker_color", sa.String(), nullable=False, server_default="#111111"
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id", "normalized_name", name="uq_place_user_name"
            ),
        )
        op.create_index("idx_place_user_name", "place", ["user_id", "normalized_name"])
        op.create_index("ix_place_user_id", "place", ["user_id"])
    else:
        columns = _column_names("place")
        additions = (
            ("address", sa.Column("address", sa.String(), nullable=True)),
            ("latitude", sa.Column("latitude", sa.Float(), nullable=True)),
            ("longitude", sa.Column("longitude", sa.Float(), nullable=True)),
            ("description", sa.Column("description", sa.String(), nullable=True)),
            (
                "marker_color",
                sa.Column(
                    "marker_color",
                    sa.String(),
                    nullable=False,
                    server_default="#111111",
                ),
            ),
        )
        for name, column in additions:
            if name not in columns:
                op.add_column("place", column)

    if "trip" not in tables:
        op.create_table(
            "trip",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("origin_id", sa.Integer(), nullable=False),
            sa.Column("destination_id", sa.Integer(), nullable=False),
            sa.Column("departed_at", sa.DateTime(), nullable=False),
            sa.Column("arrived_at", sa.DateTime(), nullable=False),
            sa.Column("transport_type", sa.String(), nullable=False),
            sa.Column("transport_detail", sa.String(), nullable=True),
            sa.Column("cost", sa.Float(), nullable=True),
            sa.Column("taxi_cost", sa.Float(), nullable=True),
            sa.Column("taxi_tariff", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "arrived_at > departed_at", name="ck_trip_positive_duration"
            ),
            sa.ForeignKeyConstraint(["destination_id"], ["place.id"]),
            sa.ForeignKeyConstraint(["origin_id"], ["place.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "idx_trip_user_route", "trip", ["user_id", "origin_id", "destination_id"]
        )
        op.create_index("ix_trip_user_id", "trip", ["user_id"])
    else:
        columns = _column_names("trip")
        if "cost" not in columns:
            op.add_column("trip", sa.Column("cost", sa.Float(), nullable=True))
            if "taxi_cost" in columns:
                op.execute(
                    sa.text(
                        "UPDATE trip SET cost = taxi_cost WHERE taxi_cost IS NOT NULL"
                    )
                )

    if "active_trip" not in tables:
        op.create_table(
            "active_trip",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("origin_id", sa.Integer(), nullable=False),
            sa.Column("departed_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["origin_id"], ["place.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )


def downgrade() -> None:
    """Remove all application tables."""

    op.drop_table("active_trip")
    op.drop_index("ix_trip_user_id", table_name="trip")
    op.drop_index("idx_trip_user_route", table_name="trip")
    op.drop_table("trip")
    op.drop_index("ix_place_user_id", table_name="place")
    op.drop_index("idx_place_user_name", table_name="place")
    op.drop_table("place")
    op.drop_index("ix_user_yandex_id", table_name="user")
    op.drop_table("user")
