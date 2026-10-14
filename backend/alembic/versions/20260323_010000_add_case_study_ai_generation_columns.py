"""add case study AI generation columns

Revision ID: 20260323_010000
Revises: 20260322_120000
Create Date: 2026-03-23 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260323_010000"
down_revision = "20260322_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cms_case_studies", sa.Column("source_project_id", sa.Integer(), nullable=True))
    op.add_column(
        "cms_case_studies",
        sa.Column("anonymization_level", sa.String(), nullable=True, server_default="full"),
    )
    op.add_column(
        "cms_case_studies",
        sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "cms_case_studies", sa.Column("generation_prompt_hash", sa.String(), nullable=True)
    )
    op.add_column(
        "cms_case_studies",
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_foreign_key(
        "fk_cms_case_studies_source_project",
        "cms_case_studies",
        "projects",
        ["source_project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_cms_case_studies_source_project_id", "cms_case_studies", ["source_project_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_cms_case_studies_source_project_id", table_name="cms_case_studies")
    op.drop_constraint("fk_cms_case_studies_source_project", "cms_case_studies", type_="foreignkey")
    op.drop_column("cms_case_studies", "schema_version")
    op.drop_column("cms_case_studies", "generation_prompt_hash")
    op.drop_column("cms_case_studies", "ai_generated")
    op.drop_column("cms_case_studies", "anonymization_level")
    op.drop_column("cms_case_studies", "source_project_id")
