"""Add workspace white-label branding columns and custom domains

Revision ID: 20260303_090000
Revises: 20260303_080000
Create Date: 2026-03-03 09:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260303_090000"
down_revision = "20260303_080000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("custom_logo_url", sa.String(), nullable=True))
    op.add_column("workspaces", sa.Column("company_name", sa.String(), nullable=True))
    op.add_column("workspaces", sa.Column("primary_color", sa.String(), nullable=True))
    op.add_column("workspaces", sa.Column("secondary_color", sa.String(), nullable=True))
    op.add_column("workspaces", sa.Column("custom_favicon_url", sa.String(), nullable=True))
    op.add_column("workspaces", sa.Column("custom_page_title", sa.String(), nullable=True))
    op.add_column("workspaces", sa.Column("custom_meta_description", sa.Text(), nullable=True))
    op.add_column(
        "workspaces",
        sa.Column("hide_powered_by", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("workspaces", sa.Column("email_sender_name", sa.String(), nullable=True))
    op.add_column("workspaces", sa.Column("email_reply_to", sa.String(), nullable=True))

    op.create_table(
        "custom_domains",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("dns_target", sa.String(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "ssl_status",
            sa.String(),
            nullable=False,
            server_default="pending_verification",
        ),
        sa.Column("verification_error", sa.Text(), nullable=True),
        sa.Column("verification_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
        sa.UniqueConstraint("domain", name="uq_custom_domains_domain"),
    )
    op.create_index(
        "ix_custom_domains_workspace_created_at",
        "custom_domains",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_custom_domains_domain_verified",
        "custom_domains",
        ["domain", "verified"],
        unique=False,
    )

    bind = op.get_bind()
    workspaces = sa.table(
        "workspaces",
        sa.column("id", sa.Integer()),
        sa.column("owner_id", sa.Integer()),
        sa.column("custom_logo_url", sa.String()),
        sa.column("company_name", sa.String()),
        sa.column("primary_color", sa.String()),
        sa.column("secondary_color", sa.String()),
    )
    users = sa.table(
        "users",
        sa.column("id", sa.Integer()),
        sa.column("custom_logo_url", sa.String()),
        sa.column("company_name", sa.String()),
        sa.column("primary_color", sa.String()),
        sa.column("secondary_color", sa.String()),
    )

    rows = bind.execute(
        sa.select(
            workspaces.c.id,
            users.c.custom_logo_url,
            users.c.company_name,
            users.c.primary_color,
            users.c.secondary_color,
        ).select_from(workspaces.join(users, workspaces.c.owner_id == users.c.id))
    ).fetchall()
    for row in rows:
        bind.execute(
            workspaces.update()
            .where(workspaces.c.id == row.id)
            .values(
                custom_logo_url=row.custom_logo_url,
                company_name=row.company_name,
                primary_color=row.primary_color,
                secondary_color=row.secondary_color,
            )
        )


def downgrade() -> None:
    op.drop_index("ix_custom_domains_domain_verified", table_name="custom_domains")
    op.drop_index("ix_custom_domains_workspace_created_at", table_name="custom_domains")
    op.drop_table("custom_domains")

    op.drop_column("workspaces", "email_reply_to")
    op.drop_column("workspaces", "email_sender_name")
    op.drop_column("workspaces", "hide_powered_by")
    op.drop_column("workspaces", "custom_meta_description")
    op.drop_column("workspaces", "custom_page_title")
    op.drop_column("workspaces", "custom_favicon_url")
    op.drop_column("workspaces", "secondary_color")
    op.drop_column("workspaces", "primary_color")
    op.drop_column("workspaces", "company_name")
    op.drop_column("workspaces", "custom_logo_url")
