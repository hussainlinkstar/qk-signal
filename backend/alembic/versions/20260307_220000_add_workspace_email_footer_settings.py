"""Add workspace email footer settings fields.

Revision ID: 20260307_220000
Revises: 20260307_130000
Create Date: 2026-03-07 22:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260307_220000"
down_revision = "20260307_130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.add_column(sa.Column("social_facebook_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("social_x_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("social_instagram_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("social_linkedin_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("social_youtube_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("social_tiktok_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("company_address", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("company_legal_name", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("company_trademark_text", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("footer_about_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("footer_blog_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("footer_support_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("footer_legal_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("footer_preferences_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("footer_privacy_url", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.drop_column("footer_privacy_url")
        batch_op.drop_column("footer_preferences_url")
        batch_op.drop_column("footer_legal_url")
        batch_op.drop_column("footer_support_url")
        batch_op.drop_column("footer_blog_url")
        batch_op.drop_column("footer_about_url")
        batch_op.drop_column("company_trademark_text")
        batch_op.drop_column("company_legal_name")
        batch_op.drop_column("company_address")
        batch_op.drop_column("social_tiktok_url")
        batch_op.drop_column("social_youtube_url")
        batch_op.drop_column("social_linkedin_url")
        batch_op.drop_column("social_instagram_url")
        batch_op.drop_column("social_x_url")
        batch_op.drop_column("social_facebook_url")
