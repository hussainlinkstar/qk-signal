"""Recompute ProjectTask.source_recommendation_key over raw input (SIGV2-1072).

The key's digest previously hashed the already-stripped ``[a-z0-9]`` slug
fragments, so any two titles collapsing onto the same slug (e.g. all non-latin
titles, or "Fix A" vs "fix  a") produced identical keys and
``sync_project_tasks`` silently dropped all but one. The digest now covers the
raw (casefolded, whitespace-normalised) title/category/description. This data
migration recomputes every persisted key from its own row so existing tasks are
not orphaned; it is deterministic and idempotent. Rows that cannot be
recomputed (NULL key) are left untouched.

Revision ID: 20261007_010000
Revises: 20261006_010000
Create Date: 2026-10-07 01:00:00.000000
"""

from alembic import op
import hashlib
import re

import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261007_010000"
down_revision = "20261006_010000"
branch_labels = None
depends_on = None


def _slug_fragment(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized[:80]


def _digest_fragment(value: str | None) -> str:
    return " ".join(str(value or "").split()).casefold()


def recompute_key(title: str, category: str, description: str | None) -> str:
    """Current algorithm, kept in lockstep with
    ``services.project_task_service._normalize_source_recommendation_key``
    (guarded by test_sigv2_1072_recommendation_chain)."""
    digest = hashlib.sha256(
        f"{_digest_fragment(category)}|{_digest_fragment(title)}|{_digest_fragment(description)}".encode(
            "utf-8"
        )
    ).hexdigest()[:12]
    return f"{_slug_fragment(category) or 'general'}:{_slug_fragment(title) or 'recommendation'}:{digest}"


def _legacy_key(title: str, category: str, description: str | None) -> str:
    """Pre-SIGV2-1072 algorithm (digest over stripped fragments), for downgrade."""
    digest = hashlib.sha256(
        f"{_slug_fragment(category)}|{_slug_fragment(title)}|{_slug_fragment(description)}".encode(
            "utf-8"
        )
    ).hexdigest()[:12]
    return (
        f"{_slug_fragment(category) or 'general'}:"
        f"{_slug_fragment(title) or 'recommendation'}:{digest}"
    )


def _rekey(key_fn) -> None:
    bind = op.get_bind()
    table = sa.table(
        "project_tasks",
        sa.column("id", sa.Integer),
        sa.column("title", sa.String),
        sa.column("category", sa.String),
        sa.column("description", sa.String),
        sa.column("source_recommendation_key", sa.String),
    )
    rows = bind.execute(
        sa.select(
            table.c.id,
            table.c.title,
            table.c.category,
            table.c.description,
            table.c.source_recommendation_key,
        ).where(table.c.source_recommendation_key.isnot(None))
    ).all()
    for row in rows:
        new_key = key_fn(row.title, row.category, row.description)
        if new_key != row.source_recommendation_key:
            bind.execute(
                table.update().where(table.c.id == row.id).values(source_recommendation_key=new_key)
            )


def upgrade() -> None:
    _rekey(recompute_key)


def downgrade() -> None:
    _rekey(_legacy_key)
