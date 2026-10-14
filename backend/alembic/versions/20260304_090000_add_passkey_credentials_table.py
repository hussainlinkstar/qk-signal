"""add passkey_credentials table

Revision ID: 20260304_090000
Revises: 20260303_090000
Create Date: 2026-03-04 09:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260304_090000"
down_revision = "20260303_090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passkey_credentials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("credential_id", sa.String(), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column(
            "sign_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "name",
            sa.String(),
            nullable=False,
            server_default="My Passkey",
        ),
        sa.Column("transports", sa.JSON(), nullable=True),
        sa.Column(
            "backed_up",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "schema_version",
            sa.String(),
            nullable=False,
            server_default="1",
        ),
    )

    op.create_index(
        "ix_passkey_credentials_user_id",
        "passkey_credentials",
        ["user_id"],
    )
    op.create_index(
        "ix_passkey_credentials_credential_id",
        "passkey_credentials",
        ["credential_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_passkey_credentials_credential_id",
        table_name="passkey_credentials",
    )
    op.drop_index(
        "ix_passkey_credentials_user_id",
        table_name="passkey_credentials",
    )
    op.drop_table("passkey_credentials")
