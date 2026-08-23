"""Pending voice field confirmation columns."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_voice_field_confirmation"
down_revision: Union[str, None] = "0003_payment_officer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("pending_voice_field", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "applications",
        sa.Column("pending_voice_value", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("applications", "pending_voice_value")
    op.drop_column("applications", "pending_voice_field")
