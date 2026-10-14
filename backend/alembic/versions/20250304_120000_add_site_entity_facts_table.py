"""Add site_entity_facts table.

Revision ID: 20250304_120000
Revises: 20250303_120000
Create Date: 2025-03-04 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250304_120000"
down_revision = "20250303_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("site_entity_facts"):
        op.create_table(
            "site_entity_facts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("site_id", sa.Integer(), nullable=False),
            sa.Column("audit_id", sa.Integer(), nullable=False),
            sa.Column("entity_name", sa.String(), nullable=False),
            sa.Column("entity_key", sa.String(), nullable=False),
            sa.Column("entity_category", sa.String(), nullable=False, server_default="Unknown"),
            sa.Column("relevance_score", sa.Float(), nullable=True),
            sa.Column("ai_importance", sa.Float(), nullable=True),
            sa.Column("source", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes("site_entity_facts")}

    if "ix_site_entity_facts_id" not in existing_indexes:
        op.create_index("ix_site_entity_facts_id", "site_entity_facts", ["id"], unique=False)
    if "ix_site_entity_facts_site_id" not in existing_indexes:
        op.create_index(
            "ix_site_entity_facts_site_id", "site_entity_facts", ["site_id"], unique=False
        )
    if "ix_site_entity_facts_audit_id" not in existing_indexes:
        op.create_index(
            "ix_site_entity_facts_audit_id", "site_entity_facts", ["audit_id"], unique=False
        )
    if "ix_site_entity_facts_created_at" not in existing_indexes:
        op.create_index(
            "ix_site_entity_facts_created_at", "site_entity_facts", ["created_at"], unique=False
        )
    if "ix_site_entity_facts_site_id_entity_key" not in existing_indexes:
        op.create_index(
            "ix_site_entity_facts_site_id_entity_key",
            "site_entity_facts",
            ["site_id", "entity_key"],
            unique=False,
        )
    if "ix_site_entity_facts_site_id_created_at" not in existing_indexes:
        op.create_index(
            "ix_site_entity_facts_site_id_created_at",
            "site_entity_facts",
            ["site_id", "created_at"],
            unique=False,
        )
    if "ix_site_entity_facts_site_id_category_created_at" not in existing_indexes:
        op.create_index(
            "ix_site_entity_facts_site_id_category_created_at",
            "site_entity_facts",
            ["site_id", "entity_category", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_site_entity_facts_site_id_category_created_at",
        table_name="site_entity_facts",
        if_exists=True,
    )
    op.drop_index(
        "ix_site_entity_facts_site_id_created_at", table_name="site_entity_facts", if_exists=True
    )
    op.drop_index(
        "ix_site_entity_facts_site_id_entity_key", table_name="site_entity_facts", if_exists=True
    )
    op.drop_index("ix_site_entity_facts_created_at", table_name="site_entity_facts", if_exists=True)
    op.drop_index("ix_site_entity_facts_audit_id", table_name="site_entity_facts", if_exists=True)
    op.drop_index("ix_site_entity_facts_site_id", table_name="site_entity_facts", if_exists=True)
    op.drop_index("ix_site_entity_facts_id", table_name="site_entity_facts", if_exists=True)
    op.drop_table("site_entity_facts", if_exists=True)
