"""Initial schema.

Revision ID: 20240924_120000
Revises:
Create Date: 2024-09-24 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20240924_120000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("external_id", sa.String(), nullable=True),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("hashed_password", sa.String(), nullable=False),
            sa.Column("role", sa.String(), nullable=False, server_default="user"),
            sa.Column("credits", sa.Integer(), nullable=False, server_default="5"),
            sa.Column(
                "notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
        )
    else:
        existing_user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "external_id" not in existing_user_columns:
            op.add_column("users", sa.Column("external_id", sa.String(), nullable=True))
    existing_user_indexes = (
        {index["name"] for index in inspector.get_indexes("users")}
        if inspector.has_table("users")
        else set()
    )
    if op.f("ix_users_external_id") not in existing_user_indexes:
        op.create_index(
            op.f("ix_users_external_id"),
            "users",
            ["external_id"],
            unique=True,
        )
    if op.f("ix_users_email") not in existing_user_indexes:
        op.create_index(
            op.f("ix_users_email"),
            "users",
            ["email"],
            unique=True,
        )

    if not inspector.has_table("audits"):
        op.create_table(
            "audits",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("url", sa.String(), nullable=False),
            sa.Column("geo_score", sa.Float(), nullable=False),
            sa.Column("full_report", sa.JSON(), nullable=False),
            sa.Column("request_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("sanitized_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not inspector.has_table("subscriptions"):
        op.create_table(
            "subscriptions",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("stripe_customer_id", sa.String(), nullable=False),
            sa.Column("plan_type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
        )
    existing_subscription_indexes = (
        {index["name"] for index in inspector.get_indexes("subscriptions")}
        if inspector.has_table("subscriptions")
        else set()
    )
    if op.f("ix_subscriptions_stripe_customer_id") not in existing_subscription_indexes:
        op.create_index(
            op.f("ix_subscriptions_stripe_customer_id"),
            "subscriptions",
            ["stripe_customer_id"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_subscriptions_stripe_customer_id"),
        table_name="subscriptions",
        if_exists=True,
    )
    op.drop_table("subscriptions", if_exists=True)
    op.drop_table("audits", if_exists=True)
    op.drop_index(op.f("ix_users_email"), table_name="users", if_exists=True)
    op.drop_index(op.f("ix_users_external_id"), table_name="users", if_exists=True)
    op.drop_table("users", if_exists=True)
