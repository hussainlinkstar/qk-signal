"""Model/inspect-based test for the ``project_brand_facts`` table (Task 6.1).

Verifies the SQLAlchemy model exposes the expected columns and FK to
``projects`` without needing a live Postgres database.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

import models
from database import Base


def test_project_brand_facts_table_columns() -> None:
    table = models.ProjectBrandFact.__table__
    assert table.name == "project_brand_facts"

    column_names = set(table.columns.keys())
    assert {
        "id",
        "project_id",
        "kind",
        "statement",
        "is_forbidden",
        "created_at",
        "schema_version",
    }.issubset(column_names)

    # statement is required, is_forbidden defaults to False
    assert table.columns["statement"].nullable is False
    assert table.columns["is_forbidden"].nullable is False


def test_project_brand_facts_foreign_key_to_projects() -> None:
    fk_target_tables = {
        fk.column.table.name
        for column in models.ProjectBrandFact.__table__.columns
        for fk in column.foreign_keys
    }
    assert "projects" in fk_target_tables


def test_project_brand_facts_created_in_metadata() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    assert "project_brand_facts" in inspector.get_table_names()
    columns = {col["name"] for col in inspector.get_columns("project_brand_facts")}
    assert {"id", "project_id", "kind", "statement", "is_forbidden"}.issubset(columns)
