"""add report annotations

Revision ID: 20260303_020000
Revises: 20260303_010000
Create Date: 2026-03-03 02:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260303_020000"
down_revision = "20260303_010000"
branch_labels = None
depends_on = None


ANNOTATION_VISIBILITY_ENUM = sa.Enum(
    "internal",
    "client_visible",
    name="annotation_visibility",
    native_enum=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "report_annotations" not in table_names:
        op.create_table(
            "report_annotations",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("audit_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("section_path", sa.String(), nullable=True),
            sa.Column("source_recommendation_key", sa.String(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column(
                "visibility",
                ANNOTATION_VISIBILITY_ENUM,
                nullable=False,
                server_default="internal",
            ),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("schema_version", sa.String(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["parent_id"], ["report_annotations.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_report_annotations_id", "report_annotations", ["id"], unique=False)
        op.create_index(
            "ix_report_annotations_audit_created",
            "report_annotations",
            ["audit_id", "created_at"],
            unique=False,
        )
        op.create_index(
            "ix_report_annotations_project_visibility",
            "report_annotations",
            ["project_id", "visibility"],
            unique=False,
        )
        op.create_index(
            "ix_report_annotations_parent_id", "report_annotations", ["parent_id"], unique=False
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "report_annotations" in table_names:
        op.drop_index("ix_report_annotations_parent_id", table_name="report_annotations")
        op.drop_index("ix_report_annotations_project_visibility", table_name="report_annotations")
        op.drop_index("ix_report_annotations_audit_created", table_name="report_annotations")
        op.drop_index("ix_report_annotations_id", table_name="report_annotations")
        op.drop_table("report_annotations")
