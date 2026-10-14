"""Add workspace/project hierarchy for agency model.

Revision ID: add_workspace_project_hierarchy
Revises: 20250309_120000
Create Date: 2026-02-24 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "add_workspace_project_hierarchy"
down_revision = "20250309_120000"
branch_labels = None
depends_on = None


WORKSPACE_ROLE_ENUM = sa.Enum(
    "ADMIN",
    "EDITOR",
    "VIEWER",
    name="workspace_user_role",
    native_enum=False,
)
OAUTH_PROVIDER_ENUM = sa.Enum(
    "google",
    "bing",
    name="oauth_provider",
    native_enum=False,
)
AUDIT_TYPE_ENUM = sa.Enum(
    "FAST",
    "SMART",
    name="audit_type",
    native_enum=False,
)


def _column_names(inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "workspaces" not in table_names:
        op.create_table(
            "workspaces",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_workspaces_id", "workspaces", ["id"], unique=False)
        op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"], unique=False)
        op.create_index(
            "ix_workspaces_owner_id_created_at",
            "workspaces",
            ["owner_id", "created_at"],
            unique=False,
        )

    if "workspace_users" not in table_names:
        op.create_table(
            "workspace_users",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role", WORKSPACE_ROLE_ENUM, nullable=False, server_default="ADMIN"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "workspace_id", "user_id", name="uq_workspace_users_workspace_user"
            ),
        )
        op.create_index("ix_workspace_users_id", "workspace_users", ["id"], unique=False)
        op.create_index(
            "ix_workspace_users_workspace_id", "workspace_users", ["workspace_id"], unique=False
        )
        op.create_index("ix_workspace_users_user_id", "workspace_users", ["user_id"], unique=False)
        op.create_index(
            "ix_workspace_users_workspace_role",
            "workspace_users",
            ["workspace_id", "role"],
            unique=False,
        )

    if "projects" not in table_names:
        op.create_table(
            "projects",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("domain_url", sa.String(), nullable=True),
            sa.Column("target_country", sa.String(), nullable=True),
            sa.Column("language", sa.String(), nullable=False, server_default="en"),
            sa.Column(
                "icp_roles",
                postgresql.ARRAY(sa.String()),
                nullable=False,
                server_default=sa.text("'{}'::text[]"),
            ),
            sa.Column("pain_points", sa.Text(), nullable=True),
            sa.Column("usp", sa.Text(), nullable=True),
            sa.Column(
                "competitors", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
            ),
            sa.Column(
                "priority_pulse_tags",
                postgresql.ARRAY(sa.String()),
                nullable=False,
                server_default=sa.text("'{}'::text[]"),
            ),
            sa.Column(
                "sme_profiles",
                postgresql.ARRAY(sa.String()),
                nullable=False,
                server_default=sa.text("'{}'::text[]"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_projects_id", "projects", ["id"], unique=False)
        op.create_index("ix_projects_workspace_id", "projects", ["workspace_id"], unique=False)
        op.create_index(
            "ix_projects_workspace_id_created_at",
            "projects",
            ["workspace_id", "created_at"],
            unique=False,
        )
        op.create_index(
            "ix_projects_workspace_domain_url",
            "projects",
            ["workspace_id", "domain_url"],
            unique=False,
        )

    if "oauth_connections" not in table_names:
        op.create_table(
            "oauth_connections",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("provider", OAUTH_PROVIDER_ENUM, nullable=False),
            sa.Column("access_token", sa.Text(), nullable=False),
            sa.Column("refresh_token", sa.Text(), nullable=True),
            sa.Column("token_type", sa.String(), nullable=True),
            sa.Column("scope", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
                onupdate=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "workspace_id",
                "provider",
                name="uq_oauth_connections_workspace_provider",
            ),
        )
        op.create_index("ix_oauth_connections_id", "oauth_connections", ["id"], unique=False)
        op.create_index(
            "ix_oauth_connections_workspace_id",
            "oauth_connections",
            ["workspace_id"],
            unique=False,
        )
        op.create_index(
            "ix_oauth_connections_workspace_provider",
            "oauth_connections",
            ["workspace_id", "provider"],
            unique=False,
        )

    if "magic_links" not in table_names:
        op.create_table(
            "magic_links",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("unique_token", sa.String(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("unique_token", name="uq_magic_links_unique_token"),
        )
        op.create_index("ix_magic_links_id", "magic_links", ["id"], unique=False)
        op.create_index("ix_magic_links_project_id", "magic_links", ["project_id"], unique=False)
        op.create_index("ix_magic_links_unique_token", "magic_links", ["unique_token"], unique=True)
        op.create_index("ix_magic_links_expires_at", "magic_links", ["expires_at"], unique=False)
        op.create_index(
            "ix_magic_links_project_id_expires_at",
            "magic_links",
            ["project_id", "expires_at"],
            unique=False,
        )

    # Refresh inspector after potential table creation.
    inspector = sa.inspect(bind)
    audit_columns = _column_names(inspector, "audits")
    audit_indexes = _index_names(inspector, "audits")
    audit_fks = inspector.get_foreign_keys("audits")

    if "project_id" not in audit_columns:
        op.add_column("audits", sa.Column("project_id", sa.Integer(), nullable=True))

    has_project_fk = any(
        fk.get("constrained_columns") == ["project_id"] and fk.get("referred_table") == "projects"
        for fk in audit_fks
    )
    if not has_project_fk:
        op.create_foreign_key(
            "fk_audits_project_id_projects",
            "audits",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if "type" not in audit_columns:
        op.add_column(
            "audits",
            sa.Column(
                "type",
                AUDIT_TYPE_ENUM,
                nullable=False,
                server_default="FAST",
            ),
        )

    if "ix_audits_project_id_created_at" not in audit_indexes:
        op.create_index(
            "ix_audits_project_id_created_at",
            "audits",
            ["project_id", "created_at"],
            unique=False,
        )

    # Backfill workspace hierarchy from legacy user/site tables.
    op.execute(
        sa.text(
            """
            INSERT INTO workspaces (name, owner_id, created_at)
            SELECT
                CASE
                    WHEN COALESCE(NULLIF(BTRIM(company_name), ''), '') <> '' THEN BTRIM(company_name) || ' Workspace'
                    ELSE split_part(email, '@', 1) || ' Workspace'
                END AS name,
                id AS owner_id,
                NOW() AS created_at
            FROM users u
            WHERE NOT EXISTS (
                SELECT 1
                FROM workspaces w
                WHERE w.owner_id = u.id
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO workspace_users (workspace_id, user_id, role, created_at)
            SELECT
                w.id AS workspace_id,
                w.owner_id AS user_id,
                'ADMIN' AS role,
                COALESCE(w.created_at, NOW()) AS created_at
            FROM workspaces w
            WHERE NOT EXISTS (
                SELECT 1
                FROM workspace_users wu
                WHERE wu.workspace_id = w.id
                  AND wu.user_id = w.owner_id
            )
            """
        )
    )

    # Ensure one default project exists for each workspace.
    op.execute(
        sa.text(
            """
            INSERT INTO projects (
                workspace_id,
                name,
                domain_url,
                target_country,
                language,
                icp_roles,
                pain_points,
                usp,
                competitors,
                priority_pulse_tags,
                sme_profiles,
                created_at
            )
            SELECT
                w.id AS workspace_id,
                'Default Project' AS name,
                NULL AS domain_url,
                NULL AS target_country,
                'en' AS language,
                '{}'::text[] AS icp_roles,
                NULL AS pain_points,
                NULL AS usp,
                '[]'::json AS competitors,
                '{}'::text[] AS priority_pulse_tags,
                '{}'::text[] AS sme_profiles,
                NOW() AS created_at
            FROM workspaces w
            WHERE NOT EXISTS (
                SELECT 1
                FROM projects p
                WHERE p.workspace_id = w.id
                  AND p.name = 'Default Project'
            )
            """
        )
    )

    # Create project records for legacy sites.
    op.execute(
        sa.text(
            """
            INSERT INTO projects (
                workspace_id,
                name,
                domain_url,
                target_country,
                language,
                icp_roles,
                pain_points,
                usp,
                competitors,
                priority_pulse_tags,
                sme_profiles,
                created_at
            )
            SELECT
                w.id AS workspace_id,
                COALESCE(NULLIF(BTRIM(s.display_name), ''), NULLIF(BTRIM(s.domain), ''), 'Project ' || s.id::text) AS name,
                CASE
                    WHEN s.domain IS NULL OR BTRIM(s.domain) = '' THEN NULL
                    WHEN s.domain ~* '^https?://' THEN LOWER(BTRIM(s.domain))
                    ELSE LOWER('https://' || BTRIM(s.domain))
                END AS domain_url,
                NULL AS target_country,
                'en' AS language,
                '{}'::text[] AS icp_roles,
                NULL AS pain_points,
                NULL AS usp,
                '[]'::json AS competitors,
                '{}'::text[] AS priority_pulse_tags,
                '{}'::text[] AS sme_profiles,
                COALESCE(s.created_at, NOW()) AS created_at
            FROM sites s
            JOIN workspaces w ON w.owner_id = s.user_id
            """
        )
    )

    # Map site-linked audits first.
    op.execute(
        sa.text(
            """
            UPDATE audits a
            SET project_id = mapped.project_id
            FROM (
                SELECT
                    s.id AS site_id,
                    (
                        SELECT p.id
                        FROM projects p
                        JOIN workspaces w2 ON w2.id = p.workspace_id
                        WHERE w2.owner_id = s.user_id
                          AND p.domain_url IS NOT DISTINCT FROM (
                              CASE
                                  WHEN s.domain IS NULL OR BTRIM(s.domain) = '' THEN NULL
                                  WHEN s.domain ~* '^https?://' THEN LOWER(BTRIM(s.domain))
                                  ELSE LOWER('https://' || BTRIM(s.domain))
                              END
                          )
                        ORDER BY p.id DESC
                        LIMIT 1
                    ) AS project_id
                FROM sites s
            ) AS mapped
            WHERE a.site_id = mapped.site_id
              AND a.project_id IS NULL
              AND mapped.project_id IS NOT NULL
            """
        )
    )

    # Fallback: assign user-level default project for remaining audits.
    op.execute(
        sa.text(
            """
            UPDATE audits a
            SET project_id = defaults.project_id
            FROM (
                SELECT
                    w.owner_id AS user_id,
                    (
                        SELECT p.id
                        FROM projects p
                        WHERE p.workspace_id = w.id
                          AND p.name = 'Default Project'
                        ORDER BY p.id DESC
                        LIMIT 1
                    ) AS project_id
                FROM workspaces w
            ) AS defaults
            WHERE a.user_id = defaults.user_id
              AND a.project_id IS NULL
              AND defaults.project_id IS NOT NULL
            """
        )
    )

    # Ensure existing rows have deterministic audit type.
    op.execute(sa.text("UPDATE audits SET type = 'FAST' WHERE type IS NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "audits" in table_names:
        audit_indexes = _index_names(inspector, "audits")
        if "ix_audits_project_id_created_at" in audit_indexes:
            op.drop_index("ix_audits_project_id_created_at", table_name="audits")

        audit_columns = _column_names(inspector, "audits")
        if "type" in audit_columns:
            op.drop_column("audits", "type")
        if "project_id" in audit_columns:
            fk_to_drop = None
            for fk in inspector.get_foreign_keys("audits"):
                if (
                    fk.get("constrained_columns") == ["project_id"]
                    and fk.get("referred_table") == "projects"
                ):
                    fk_to_drop = fk.get("name")
                    break
            if fk_to_drop:
                op.drop_constraint(fk_to_drop, "audits", type_="foreignkey")
            op.drop_column("audits", "project_id")

    if "magic_links" in table_names:
        op.drop_index(
            "ix_magic_links_project_id_expires_at", table_name="magic_links", if_exists=True
        )
        op.drop_index("ix_magic_links_expires_at", table_name="magic_links", if_exists=True)
        op.drop_index("ix_magic_links_unique_token", table_name="magic_links", if_exists=True)
        op.drop_index("ix_magic_links_project_id", table_name="magic_links", if_exists=True)
        op.drop_index("ix_magic_links_id", table_name="magic_links", if_exists=True)
        op.drop_table("magic_links")

    if "oauth_connections" in table_names:
        op.drop_index(
            "ix_oauth_connections_workspace_provider",
            table_name="oauth_connections",
            if_exists=True,
        )
        op.drop_index(
            "ix_oauth_connections_workspace_id", table_name="oauth_connections", if_exists=True
        )
        op.drop_index("ix_oauth_connections_id", table_name="oauth_connections", if_exists=True)
        op.drop_table("oauth_connections")

    if "projects" in table_names:
        op.drop_index("ix_projects_workspace_domain_url", table_name="projects", if_exists=True)
        op.drop_index("ix_projects_workspace_id_created_at", table_name="projects", if_exists=True)
        op.drop_index("ix_projects_workspace_id", table_name="projects", if_exists=True)
        op.drop_index("ix_projects_id", table_name="projects", if_exists=True)
        op.drop_table("projects")

    if "workspace_users" in table_names:
        op.drop_index(
            "ix_workspace_users_workspace_role", table_name="workspace_users", if_exists=True
        )
        op.drop_index("ix_workspace_users_user_id", table_name="workspace_users", if_exists=True)
        op.drop_index(
            "ix_workspace_users_workspace_id", table_name="workspace_users", if_exists=True
        )
        op.drop_index("ix_workspace_users_id", table_name="workspace_users", if_exists=True)
        op.drop_table("workspace_users")

    if "workspaces" in table_names:
        op.drop_index("ix_workspaces_owner_id_created_at", table_name="workspaces", if_exists=True)
        op.drop_index("ix_workspaces_owner_id", table_name="workspaces", if_exists=True)
        op.drop_index("ix_workspaces_id", table_name="workspaces", if_exists=True)
        op.drop_table("workspaces")
