"""add guest_audit_records table

Revision ID: 20260323_020000
Revises: 20260323_010000
Create Date: 2026-03-23 02:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260323_020000"
down_revision = "20260323_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guest_audit_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ip_hash", sa.String(), nullable=False),
        sa.Column("target_url", sa.String(), nullable=True),
        sa.Column("target_name", sa.String(), nullable=True),
        sa.Column("audit_target_type", sa.String(), nullable=False, server_default="website"),
        sa.Column("seo_score", sa.Float(), nullable=True),
        sa.Column("geo_score", sa.Float(), nullable=True),
        sa.Column("aeo_score", sa.Float(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("findings_summary", sa.JSON(), nullable=True),
        sa.Column("entity_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("competitor_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claim_token", sa.String(), nullable=False, unique=True),
        sa.Column(
            "claimed_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("referrer", sa.String(), nullable=True),
        sa.Column("user_agent_hash", sa.String(), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_guest_audit_records_ip_hash", "guest_audit_records", ["ip_hash"])
    op.create_index("ix_guest_audit_records_claim_token", "guest_audit_records", ["claim_token"])
    op.create_index("ix_guest_audit_records_created_at", "guest_audit_records", ["created_at"])
    op.create_index("ix_guest_audit_records_request_id", "guest_audit_records", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_guest_audit_records_request_id", table_name="guest_audit_records")
    op.drop_index("ix_guest_audit_records_created_at", table_name="guest_audit_records")
    op.drop_index("ix_guest_audit_records_claim_token", table_name="guest_audit_records")
    op.drop_index("ix_guest_audit_records_ip_hash", table_name="guest_audit_records")
    op.drop_table("guest_audit_records")
