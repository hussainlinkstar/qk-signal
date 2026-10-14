"""add sites table and audit site linkage

Revision ID: 20250223_120000
Revises: 20250222_120000
Create Date: 2025-02-23 12:00:00.000000
"""

from typing import Sequence, Union
from urllib.parse import urlparse

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20250223_120000"
down_revision: Union[str, None] = "20250222_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _extract_domain(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().lower()
    return host or None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("sites"):
        op.create_table(
            "sites",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("domain", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "domain", name="uq_sites_user_domain"),
        )
        op.create_index(op.f("ix_sites_id"), "sites", ["id"], unique=False)
        op.create_index(op.f("ix_sites_user_id"), "sites", ["user_id"], unique=False)
        op.create_index(op.f("ix_sites_domain"), "sites", ["domain"], unique=False)

    audit_columns = {column["name"] for column in inspector.get_columns("audits")}
    if "site_id" not in audit_columns:
        op.add_column("audits", sa.Column("site_id", sa.Integer(), nullable=True))
        op.create_index(op.f("ix_audits_site_id"), "audits", ["site_id"], unique=False)

    metadata = sa.MetaData()
    audits = sa.Table("audits", metadata, autoload_with=bind)
    sites = sa.Table("sites", metadata, autoload_with=bind)

    rows = bind.execute(
        sa.select(audits.c.id, audits.c.user_id, audits.c.url, audits.c.site_id)
    ).fetchall()
    site_cache: dict[tuple[int, str], int] = {}

    for row in rows:
        if row.site_id is not None:
            continue

        domain = _extract_domain(row.url)
        if row.user_id is None or not domain:
            continue

        key = (row.user_id, domain)
        site_id = site_cache.get(key)

        if site_id is None:
            existing_site_id = bind.execute(
                sa.select(sites.c.id).where(
                    sites.c.user_id == row.user_id,
                    sites.c.domain == domain,
                )
            ).scalar()

            if existing_site_id is None:
                inserted = bind.execute(
                    sites.insert().values(
                        user_id=row.user_id,
                        domain=domain,
                        display_name=domain,
                    )
                )
                site_id = inserted.inserted_primary_key[0]
            else:
                site_id = existing_site_id
            site_cache[key] = site_id

        bind.execute(audits.update().where(audits.c.id == row.id).values(site_id=site_id))

    op.create_foreign_key(
        "fk_audits_site_id_sites",
        "audits",
        "sites",
        ["site_id"],
        ["id"],
    )

    op.create_index(
        "ix_audits_site_id_created_at",
        "audits",
        ["site_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audits_site_id_created_at", table_name="audits", if_exists=True)
    op.drop_constraint("fk_audits_site_id_sites", "audits", type_="foreignkey")
    op.drop_index(op.f("ix_audits_site_id"), table_name="audits", if_exists=True)
    op.drop_column("audits", "site_id", if_exists=True)

    op.drop_index(op.f("ix_sites_domain"), table_name="sites", if_exists=True)
    op.drop_index(op.f("ix_sites_user_id"), table_name="sites", if_exists=True)
    op.drop_index(op.f("ix_sites_id"), table_name="sites", if_exists=True)
    op.drop_table("sites")
