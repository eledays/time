"""Add saved route snapshots with revocable public links.

Revision ID: 20260916_0003
Revises: 20260914_0002
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0003"
down_revision: str | None = "20260914_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create storage for user-named route snapshots."""

    op.create_table(
        "saved_route",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("origin_name", sa.String(), nullable=False),
        sa.Column("destination_name", sa.String(), nullable=False),
        sa.Column("route_data", sa.Text(), nullable=False),
        sa.Column("public_token", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_saved_route_user_created",
        "saved_route",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_saved_route_public_token", "saved_route", ["public_token"], unique=True
    )
    op.create_index("ix_saved_route_user_id", "saved_route", ["user_id"])


def downgrade() -> None:
    """Remove saved route snapshots."""

    op.drop_index("ix_saved_route_user_id", table_name="saved_route")
    op.drop_index("ix_saved_route_public_token", table_name="saved_route")
    op.drop_index("idx_saved_route_user_created", table_name="saved_route")
    op.drop_table("saved_route")
