"""Модели пользователей, мест и записанных перемещений."""

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


def utc_now() -> datetime:
    """Вернуть текущее время UTC с указанием часового пояса."""

    return datetime.now(UTC)


class User(db.Model):
    """Пользователь, полученный из профиля Яндекс ID."""

    id: Mapped[int] = mapped_column(primary_key=True)
    yandex_id: Mapped[str] = mapped_column(unique=True, index=True)
    display_name: Mapped[str]
    timezone: Mapped[str | None]
    terms_version: Mapped[str | None]
    terms_accepted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    places: Mapped[list["Place"]] = relationship(back_populates="user")
    trips: Mapped[list["Trip"]] = relationship(back_populates="user")
    active_trip: Mapped[Optional["ActiveTrip"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Place(db.Model):
    """Сохранённое пользователем место с нормализованным названием."""

    __table_args__ = (
        UniqueConstraint("user_id", "normalized_name", name="uq_place_user_name"),
        Index("idx_place_user_name", "user_id", "normalized_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    name: Mapped[str]
    normalized_name: Mapped[str]
    address: Mapped[str | None]
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
    description: Mapped[str | None]
    marker_color: Mapped[str] = mapped_column(default="#111111")
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    user: Mapped[User] = relationship(back_populates="places")


class Trip(db.Model):
    """Один завершённый отрезок пути."""

    __table_args__ = (
        CheckConstraint("arrived_at > departed_at", name="ck_trip_positive_duration"),
        Index("idx_trip_user_route", "user_id", "origin_id", "destination_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    origin_id: Mapped[int] = mapped_column(ForeignKey("place.id"))
    destination_id: Mapped[int] = mapped_column(ForeignKey("place.id"))
    departed_at: Mapped[datetime]
    arrived_at: Mapped[datetime]
    transport_type: Mapped[str]
    transport_detail: Mapped[str | None]
    cost: Mapped[float | None]
    taxi_cost: Mapped[float | None]
    taxi_tariff: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    user: Mapped[User] = relationship(back_populates="trips")
    origin: Mapped[Place] = relationship(foreign_keys=[origin_id])
    destination: Mapped[Place] = relationship(foreign_keys=[destination_id])

    @property
    def duration_minutes(self) -> int:
        """Вернуть продолжительность поездки в целых минутах."""

        return round((self.arrived_at - self.departed_at).total_seconds() / 60)


class ActiveTrip(db.Model):
    """Незавершённая поездка, ожидающая конечную точку."""

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), unique=True)
    origin_id: Mapped[int] = mapped_column(ForeignKey("place.id"))
    departed_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

    user: Mapped[User] = relationship(back_populates="active_trip")
    origin: Mapped[Place] = relationship()
