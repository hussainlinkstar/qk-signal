"""add project competitive intelligence

Revision ID: 20260302_230000
Revises: 20260302_210000
Create Date: 2026-03-02 23:00:00.000000
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260302_230000"
down_revision = "20260302_210000"
branch_labels = None
depends_on = None


COMPETITIVE_DIGEST_FREQUENCY_ENUM = sa.Enum(
    "off",
    "weekly",
    "monthly",
    name="competitive_digest_frequency",
    native_enum=False,
)


def _normalize_competitor_url(value: str) -> tuple[str, str]:
    candidate = str(value or "").strip()
    if not candidate:
        raise ValueError("missing competitor")
    normalized_url = (
        candidate if candidate.startswith(("http://", "https://")) else f"https://{candidate}"
    )
    parsed = urlparse(normalized_url)
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("missing domain")
    normalized_domain = hostname[4:] if hostname.startswith("www.") else hostname
    path = (parsed.path or "").rstrip("/")
    target_url = f"https://{normalized_domain}{path}" if path else f"https://{normalized_domain}"
    return target_url, normalized_domain


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    project_columns = {column["name"] for column in inspector.get_columns("projects")}

    with op.batch_alter_table("projects") as batch_op:
        if "auto_competitor_audits_enabled" not in project_columns:
            batch_op.add_column(
                sa.Column(
                    "auto_competitor_audits_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default="true",
                )
            )
        if "competitive_digest_frequency" not in project_columns:
            batch_op.add_column(
                sa.Column(
                    "competitive_digest_frequency",
                    COMPETITIVE_DIGEST_FREQUENCY_ENUM,
                    nullable=False,
                    server_default="weekly",
                )
            )

    if "project_competitors" not in table_names:
        op.create_table(
            "project_competitors",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("target_url", sa.String(), nullable=False),
            sa.Column("normalized_domain", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("auto_audit_enabled", sa.Boolean(), nullable=False, server_default="true"),
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
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "project_id", "normalized_domain", name="uq_project_competitors_project_domain"
            ),
        )
        op.create_index("ix_project_competitors_id", "project_competitors", ["id"], unique=False)
        op.create_index(
            "ix_project_competitors_project_created",
            "project_competitors",
            ["project_id", "created_at"],
            unique=False,
        )
        op.create_index(
            "ix_project_competitors_normalized_domain",
            "project_competitors",
            ["normalized_domain"],
            unique=False,
        )

    if "project_competitor_snapshots" not in table_names:
        op.create_table(
            "project_competitor_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("competitor_id", sa.Integer(), nullable=False),
            sa.Column("source_audit_id", sa.Integer(), nullable=False),
            sa.Column("competitor_audit_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.Column("geo_score", sa.Float(), nullable=True),
            sa.Column("seo_score", sa.Float(), nullable=True),
            sa.Column("aeo_score", sa.Float(), nullable=True),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
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
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["competitor_id"], ["project_competitors.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["source_audit_id"], ["audits.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["competitor_audit_id"], ["audits.id"], ondelete="SET NULL"),
            sa.UniqueConstraint(
                "project_id",
                "competitor_id",
                "source_audit_id",
                name="uq_project_competitor_snapshots_source_competitor",
            ),
        )
        op.create_index(
            "ix_project_competitor_snapshots_id",
            "project_competitor_snapshots",
            ["id"],
            unique=False,
        )
        op.create_index(
            "ix_project_competitor_snapshots_project_created",
            "project_competitor_snapshots",
            ["project_id", "created_at"],
            unique=False,
        )
        op.create_index(
            "ix_project_competitor_snapshots_source_audit",
            "project_competitor_snapshots",
            ["source_audit_id"],
            unique=False,
        )
        op.create_index(
            "ix_project_competitor_snapshots_competitor",
            "project_competitor_snapshots",
            ["competitor_id"],
            unique=False,
        )
        op.create_index(
            "ix_project_competitor_snapshots_status",
            "project_competitor_snapshots",
            ["status"],
            unique=False,
        )

    if "project_competitive_digest_logs" not in table_names:
        op.create_table(
            "project_competitive_digest_logs",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("source_audit_id", sa.Integer(), nullable=False),
            sa.Column("frequency", sa.String(), nullable=False, server_default="weekly"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_audit_id"], ["audits.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "source_audit_id", name="uq_project_competitive_digest_logs_source_audit"
            ),
        )
        op.create_index(
            "ix_project_competitive_digest_logs_id",
            "project_competitive_digest_logs",
            ["id"],
            unique=False,
        )
        op.create_index(
            "ix_project_competitive_digest_logs_project_created",
            "project_competitive_digest_logs",
            ["project_id", "created_at"],
            unique=False,
        )

    project_competitors_columns = {
        column["name"] for column in inspector.get_columns("project_competitors")
    }
    has_project_competitors = "project_competitors" in table_names or bool(
        project_competitors_columns
    )
    if has_project_competitors:
        insert_stmt = sa.text(
            """
            INSERT INTO project_competitors (
                project_id,
                target_url,
                normalized_domain,
                display_name,
                auto_audit_enabled
            ) VALUES (
                :project_id,
                :target_url,
                :normalized_domain,
                :display_name,
                true
            )
            """
        )
        existing_rows = (
            bind.execute(sa.text("SELECT project_id, normalized_domain FROM project_competitors"))
            .mappings()
            .all()
        )
        existing_pairs = {
            (int(row["project_id"]), str(row["normalized_domain"])) for row in existing_rows
        }
        project_rows = (
            bind.execute(sa.text("SELECT id, competitors FROM projects")).mappings().all()
        )
        for row in project_rows:
            raw_competitors = row["competitors"]
            if isinstance(raw_competitors, str):
                try:
                    raw_competitors = json.loads(raw_competitors)
                except json.JSONDecodeError:
                    raw_competitors = []
            if not isinstance(raw_competitors, list):
                continue
            seen_domains: set[str] = set()
            for competitor in raw_competitors[:5]:
                if not isinstance(competitor, str) or not competitor.strip():
                    continue
                try:
                    target_url, normalized_domain = _normalize_competitor_url(competitor)
                except ValueError:
                    continue
                if normalized_domain in seen_domains:
                    continue
                seen_domains.add(normalized_domain)
                pair = (int(row["id"]), normalized_domain)
                if pair in existing_pairs:
                    continue
                bind.execute(
                    insert_stmt,
                    {
                        "project_id": int(row["id"]),
                        "target_url": target_url,
                        "normalized_domain": normalized_domain,
                        "display_name": normalized_domain,
                    },
                )
                existing_pairs.add(pair)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    project_columns = {column["name"] for column in inspector.get_columns("projects")}

    if "project_competitive_digest_logs" in table_names:
        op.drop_index(
            "ix_project_competitive_digest_logs_project_created",
            table_name="project_competitive_digest_logs",
        )
        op.drop_index(
            "ix_project_competitive_digest_logs_id", table_name="project_competitive_digest_logs"
        )
        op.drop_table("project_competitive_digest_logs")

    if "project_competitor_snapshots" in table_names:
        op.drop_index(
            "ix_project_competitor_snapshots_status", table_name="project_competitor_snapshots"
        )
        op.drop_index(
            "ix_project_competitor_snapshots_competitor", table_name="project_competitor_snapshots"
        )
        op.drop_index(
            "ix_project_competitor_snapshots_source_audit",
            table_name="project_competitor_snapshots",
        )
        op.drop_index(
            "ix_project_competitor_snapshots_project_created",
            table_name="project_competitor_snapshots",
        )
        op.drop_index(
            "ix_project_competitor_snapshots_id", table_name="project_competitor_snapshots"
        )
        op.drop_table("project_competitor_snapshots")

    if "project_competitors" in table_names:
        op.drop_index("ix_project_competitors_normalized_domain", table_name="project_competitors")
        op.drop_index("ix_project_competitors_project_created", table_name="project_competitors")
        op.drop_index("ix_project_competitors_id", table_name="project_competitors")
        op.drop_table("project_competitors")

    with op.batch_alter_table("projects") as batch_op:
        if "competitive_digest_frequency" in project_columns:
            batch_op.drop_column("competitive_digest_frequency")
        if "auto_competitor_audits_enabled" in project_columns:
            batch_op.drop_column("auto_competitor_audits_enabled")
