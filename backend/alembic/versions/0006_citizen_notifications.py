"""Citizen status notification inbox (simulated local delivery)."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_citizen_notifications"
down_revision: Union[str, None] = "0005_dynamic_otp_registration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "citizen_notifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "application_id",
            sa.String(length=36),
            sa.ForeignKey("applications.id"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("recipient_mobile_last4", sa.String(length=4), nullable=True),
        sa.Column("recipient_email", sa.String(length=255), nullable=True),
        sa.Column(
            "channels",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("delivery_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_citizen_notifications_application_id",
        "citizen_notifications",
        ["application_id"],
    )
    op.create_index(
        "ix_citizen_notifications_event_type",
        "citizen_notifications",
        ["event_type"],
    )
    op.create_index(
        "ix_citizen_notifications_created_at",
        "citizen_notifications",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_citizen_notifications_created_at", table_name="citizen_notifications")
    op.drop_index("ix_citizen_notifications_event_type", table_name="citizen_notifications")
    op.drop_index("ix_citizen_notifications_application_id", table_name="citizen_notifications")
    op.drop_table("citizen_notifications")
