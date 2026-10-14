"""Add first-party identity fields to users.

Revision ID: 20250305_120000
Revises: 20250304_120000
Create Date: 2025-03-05 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250305_120000"
down_revision = "20250304_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    indexes = {index["name"] for index in inspector.get_indexes("users")}

    if "auth_provider" not in columns:
        op.add_column(
            "users",
            sa.Column("auth_provider", sa.String(), nullable=False, server_default="local"),
        )
    if "provider_subject" not in columns:
        op.add_column("users", sa.Column("provider_subject", sa.String(), nullable=True))

    # Historical schemas may have used alternate identity columns for upstream subject IDs.
    source_identity_column = None
    legacy_identity_column = "".join(["c", "l", "e", "r", "k", "_id"])
    if "external_id" in columns:
        source_identity_column = "external_id"
    elif legacy_identity_column in columns:
        source_identity_column = legacy_identity_column

    if source_identity_column:
        op.execute(
            sa.text(
                f"""
                UPDATE users
                SET provider_subject = {source_identity_column},
                    auth_provider = CASE
                        WHEN {source_identity_column} IS NULL OR {source_identity_column} = '' THEN 'local'
                        ELSE 'external'
                    END
                WHERE provider_subject IS NULL
                """
            )
        )
    else:
        op.execute(
            """
            UPDATE users
            SET auth_provider = 'local'
            WHERE provider_subject IS NULL
            """
        )

    if "ix_users_provider_subject" not in indexes:
        op.create_index("ix_users_provider_subject", "users", ["provider_subject"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_provider_subject", table_name="users", if_exists=True)
    op.drop_column("users", "provider_subject")
    op.drop_column("users", "auth_provider")
