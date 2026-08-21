"""Initial schema extensions for payments, receipts, and processing status."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_payment_officer"
down_revision: Union[str, None] = "0002_journey"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column(
            "processing_status",
            sa.String(length=64),
            nullable=False,
            server_default="DRAFT",
        ),
    )
    op.add_column("applications", sa.Column("correction_notes", sa.Text(), nullable=True))
    op.add_column("applications", sa.Column("fee_amount_paise", sa.Integer(), nullable=True))
    op.add_column(
        "applications",
        sa.Column("fee_currency", sa.String(length=8), nullable=False, server_default="INR"),
    )
    op.add_column(
        "applications",
        sa.Column("payment_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("applications", sa.Column("payment_ref", sa.String(length=64), nullable=True))
    op.add_column(
        "applications",
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_applications_processing_status", "applications", ["processing_status"])

    op.add_column("documents", sa.Column("verification_status", sa.String(length=32), nullable=True))
    op.add_column("documents", sa.Column("verification_reason", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("ocr_provider", sa.String(length=64), nullable=True))

    op.create_table(
        "payments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("application_id", sa.String(length=36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("payment_ref", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=128), nullable=True),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payments_application_id", "payments", ["application_id"])
    op.create_index("ix_payments_outcome", "payments", ["outcome"])

    op.create_table(
        "receipts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("receipt_id", sa.String(length=64), nullable=False),
        sa.Column("application_id", sa.String(length=36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("service_code", sa.String(length=64), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("payment_ref", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_receipts_receipt_id", "receipts", ["receipt_id"], unique=True)
    op.create_index("ix_receipts_application_id", "receipts", ["application_id"])


def downgrade() -> None:
    op.drop_table("receipts")
    op.drop_table("payments")
    op.drop_column("documents", "ocr_provider")
    op.drop_column("documents", "verification_reason")
    op.drop_column("documents", "verification_status")
    op.drop_index("ix_applications_processing_status", table_name="applications")
    op.drop_column("applications", "escalated")
    op.drop_column("applications", "payment_ref")
    op.drop_column("applications", "payment_completed")
    op.drop_column("applications", "fee_currency")
    op.drop_column("applications", "fee_amount_paise")
    op.drop_column("applications", "correction_notes")
    op.drop_column("applications", "processing_status")
