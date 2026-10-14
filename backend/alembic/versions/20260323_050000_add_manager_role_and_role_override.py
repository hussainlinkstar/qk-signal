"""add MANAGER workspace role and project role_override column

Revision ID: 20260323_050000
Revises: 20260323_040000
Create Date: 2026-03-23 05:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_050000"
down_revision = "20260323_040000"
branch_labels = None
depends_on = None

_ENUM_NAME = "workspacerole"
_NEW_VALUE = "MANAGER"


def upgrade() -> None:
    # WorkspaceRole uses native_enum=False (varchar + CHECK constraint),
    # so there is no PostgreSQL enum type to alter.  MANAGER is already
    # a valid Python enum value, we only need the new column.
    op.add_column(
        "workspace_user_project_access",
        sa.Column(
            "role_override",
            sa.VARCHAR(length=255),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("workspace_user_project_access", "role_override")
