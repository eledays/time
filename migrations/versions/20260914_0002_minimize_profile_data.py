"""Remove profile fields that are unnecessary for the service.

Revision ID: 20260914_0002
Revises: 20260914_0001
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0002"
down_revision: str | None = "20260914_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Delete previously stored email and avatar URLs, then remove their columns."""

    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("user")}
    removable_columns = [name for name in ("email", "avatar_url") if name in columns]
    for column_name in removable_columns:
        op.execute(sa.text(f'UPDATE "user" SET "{column_name}" = NULL'))
    if removable_columns:
        with op.batch_alter_table("user") as batch_op:
            for column_name in removable_columns:
                batch_op.drop_column(column_name)


def downgrade() -> None:
    """Restore nullable legacy columns without restoring deleted values."""

    with op.batch_alter_table("user") as batch_op:
        batch_op.add_column(sa.Column("avatar_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("email", sa.String(), nullable=True))
