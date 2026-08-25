"""Synthetic citizen table and auth_step for dynamic OTP / registration."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_dynamic_otp_registration"
down_revision: Union[str, None] = "0004_voice_field_confirmation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("auth_step", sa.String(length=32), nullable=True),
    )
    op.create_table(
        "synthetic_citizens",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("persona_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("mobile", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("persona_id", name="uq_synthetic_citizen_persona_id"),
        sa.UniqueConstraint("mobile", name="uq_synthetic_citizen_mobile"),
    )
    op.create_index("ix_synthetic_citizens_mobile", "synthetic_citizens", ["mobile"])


def downgrade() -> None:
    op.drop_index("ix_synthetic_citizens_mobile", table_name="synthetic_citizens")
    op.drop_table("synthetic_citizens")
    op.drop_column("applications", "auth_step")
