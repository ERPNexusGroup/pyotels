"""add_housekeeping_and_billing_sync_fields

Revision ID: a1b2c3d4e5f6
Revises: f32e921e3203
Create Date: 2026-11-14 22:36:30.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f32e921e3203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rooms", sa.Column("last_cleaned_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE rooms SET last_cleaned_at = CURRENT_TIMESTAMP WHERE last_cleaned_at IS NULL")
    op.add_column("housekeeping_status", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("reservations", sa.Column("otelms_balance", sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column("reservations", sa.Column("deep_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("reservations", "deep_synced_at")
    op.drop_column("reservations", "otelms_balance")
    op.drop_column("housekeeping_status", "notes")
    op.drop_column("rooms", "last_cleaned_at")
