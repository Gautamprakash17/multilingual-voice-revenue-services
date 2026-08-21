"""Add applications, conversation_sessions, and documents tables."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_journey"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("application_id", sa.String(length=32), nullable=False),
        sa.Column("service_code", sa.String(length=64), nullable=False),
        sa.Column("applicant_id", sa.String(length=64), nullable=True),
        sa.Column("current_state", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column(
            "form_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("consent_granted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correcting_field", sa.String(length=64), nullable=True),
        sa.Column("auth_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_mobile", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_applications_application_id", "applications", ["application_id"], unique=True)
    op.create_index("ix_applications_applicant_id", "applications", ["applicant_id"])
    op.create_index("ix_applications_current_state", "applications", ["current_state"])

    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("application_id", sa.String(length=36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("current_state", sa.String(length=64), nullable=False),
        sa.Column("access_token", sa.String(length=64), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_conversation_sessions_application_id", "conversation_sessions", ["application_id"])
    op.create_index(
        "ix_conversation_sessions_access_token",
        "conversation_sessions",
        ["access_token"],
        unique=True,
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("application_id", sa.String(length=36), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("document_code", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=128), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("application_id", "document_code", name="uq_app_document_code"),
    )
    op.create_index("ix_documents_application_id", "documents", ["application_id"])
    op.create_index("ix_documents_storage_key", "documents", ["storage_key"], unique=True)


def downgrade() -> None:
    op.drop_table("documents")
    op.drop_table("conversation_sessions")
    op.drop_table("applications")
