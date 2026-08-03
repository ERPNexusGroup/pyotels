"""fix sync_logs id type for sqlite autoincrement

Revision ID: 28e062238471
Revises: 4b8144c8fcbe
Create Date: 2026-08-02 20:27:31.970785

SQLite solo autoincrementa con `INTEGER PRIMARY KEY`; la tabla fue creada
con `BIGINT` y los INSERT fallaban con `NOT NULL constraint failed: sync_logs.id`.
La tabla estaba vacía, así que drop + recreate no pierde datos.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28e062238471'
down_revision: Union[str, Sequence[str], None] = '4b8144c8fcbe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("sync_logs")
    op.create_table(
        "sync_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hotel_id", sa.String(length=64), nullable=False),
        sa.Column("sync_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("records_processed", sa.Integer(), nullable=False),
        sa.Column("records_created", sa.Integer(), nullable=False),
        sa.Column("records_updated", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Text(), nullable=True),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["hotel_id"], ["hotels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_logs_hotel_id", "sync_logs", ["hotel_id"])
    op.create_index("ix_sync_logs_sync_type", "sync_logs", ["sync_type"])
    op.create_index("ix_sync_logs_status", "sync_logs", ["status"])
    op.create_index("ix_sync_logs_started_at", "sync_logs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_sync_logs_started_at", table_name="sync_logs")
    op.drop_index("ix_sync_logs_status", table_name="sync_logs")
    op.drop_index("ix_sync_logs_sync_type", table_name="sync_logs")
    op.drop_index("ix_sync_logs_hotel_id", table_name="sync_logs")
    op.drop_table("sync_logs")
