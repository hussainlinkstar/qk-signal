"""Add SEO and AEO score columns to audits and backfill from reports.

Revision ID: 20250219_120000
Revises: 20250218_120000
Create Date: 2025-02-19 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250219_120000"
down_revision = "20250218_120000"
branch_labels = None
depends_on = None


def _extract_score(report: dict, score_key: str) -> float | None:
    if not isinstance(report, dict):
        return None

    scores = report.get("scores")
    if isinstance(scores, dict):
        value = scores.get(score_key)
        if isinstance(value, (int, float)):
            return float(value)

    analysis = report.get("analysis")
    if isinstance(analysis, dict):
        analysis_value = analysis.get(f"{score_key}_score")
        if isinstance(analysis_value, dict):
            score = analysis_value.get("score")
            if isinstance(score, (int, float)):
                return float(score)
        if isinstance(analysis_value, (int, float)):
            return float(analysis_value)

    return None


def upgrade() -> None:
    op.add_column("audits", sa.Column("seo_score", sa.Float(), nullable=True))
    op.add_column("audits", sa.Column("aeo_score", sa.Float(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, full_report FROM audits")).mappings().all()

    for row in rows:
        full_report = row.get("full_report")
        seo_score = _extract_score(full_report, "seo")
        aeo_score = _extract_score(full_report, "aeo")

        if seo_score is None and aeo_score is None:
            continue

        bind.execute(
            sa.text(
                "UPDATE audits SET seo_score = :seo_score, aeo_score = :aeo_score WHERE id = :id"
            ),
            {
                "id": row["id"],
                "seo_score": seo_score,
                "aeo_score": aeo_score,
            },
        )


def downgrade() -> None:
    op.drop_column("audits", "aeo_score")
    op.drop_column("audits", "seo_score")
