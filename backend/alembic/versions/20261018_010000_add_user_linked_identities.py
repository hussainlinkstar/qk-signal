"""Add user_linked_identities (SIGV2-1257).

SIGV2-1239 correctly stopped the OAuth callback from auto-linking a Microsoft
identity to an existing account on an unverified email claim, which left a
user with an email/password account no way to use Microsoft sign-in at all.
The recovery path is an explicit link proven with the account's own password,
and this table is where the resulting provider identity lives.

It cannot live in ``users.auth_provider`` / ``users.provider_subject``:
``auth/token_verifier.py`` rewrites both columns to the access token's subject
on every authenticated request, so a link stored there does not survive the
user's next API call.

Additive only: one new table with two unique constraints, nothing dropped,
renamed, retyped or backfilled.

Revision ID: 20261018_010000
Revises: 20261017_010000
Create Date: 2026-10-18 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261018_010000"
down_revision = "20261017_010000"
branch_labels = None
depends_on = None

TABLE_NAME = "user_linked_identities"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE_NAME in set(inspector.get_table_names()):
        return

    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "provider",
            "subject",
            name="uq_user_linked_identity_provider_subject",
        ),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            name="uq_user_linked_identity_user_provider",
        ),
    )
    op.create_index(
        "ix_user_linked_identities_user_id",
        TABLE_NAME,
        ["user_id"],
    )


def downgrade() -> None:
    """Drop the table.

    Reversible in shape, lossy in content: every manual link is recorded only
    here, so dropping it means each affected customer has to link again.
    Never run against a live database (AGENTS.md 4.2).
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE_NAME not in set(inspector.get_table_names()):
        return

    op.drop_index("ix_user_linked_identities_user_id", table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
