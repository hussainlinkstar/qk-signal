"""GA4 sync targets come from the mapping the settings UI actually writes.

Two tables held a GA4 property. Project Settings writes ``project_data_sources``
with source_type ``google_analytics_4``, including provider catalog discovery.
The monitoring worker read ``project_ga4_configs``, which no endpoint ever
populated, so a customer could pick their property, see it saved, and never get
a single sync.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from monitoring_worker import _normalize_ga4_property_id, _resolve_ga4_targets


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _project(db: Session, name: str) -> models.Project:
    owner = models.User(email=f"{name.replace(' ', '-').lower()}@example.com", hashed_password="x")
    db.add(owner)
    db.flush()
    workspace = models.Workspace(name=f"{name} workspace", owner_id=owner.id)
    db.add(workspace)
    db.flush()
    project = models.Project(workspace_id=workspace.id, name=name, language="en")
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _data_source(
    db: Session, project_id: int, source_id: str | None, is_active: bool = True
) -> None:
    db.add(
        models.ProjectDataSource(
            project_id=project_id,
            provider=models.OAuthProvider.GOOGLE,
            source_type=models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
            source_id=source_id,
            is_active=is_active,
        )
    )
    db.commit()


def test_property_selected_in_settings_is_picked_up_by_the_sync(db: Session) -> None:
    """The regression: this mapping used to be invisible to the worker."""
    project = _project(db, "Settings mapped")
    _data_source(db, project.id, "properties/123456789")

    targets = _resolve_ga4_targets(db)

    assert [(t.project_id, t.ga4_property_id) for t in targets] == [
        (project.id, "properties/123456789")
    ]


def test_bare_numeric_property_id_from_the_catalog_is_normalized(db: Session) -> None:
    project = _project(db, "Bare numeric")
    _data_source(db, project.id, "123456789")

    targets = _resolve_ga4_targets(db)

    assert targets[0].ga4_property_id == "properties/123456789"


def test_inactive_or_unusable_mappings_are_skipped(db: Session) -> None:
    inactive = _project(db, "Inactive")
    _data_source(db, inactive.id, "properties/1", is_active=False)

    empty = _project(db, "No property chosen")
    _data_source(db, empty.id, None)

    hostile = _project(db, "Hostile value")
    # The id is interpolated into the GA4 Data API URL, so a path segment must
    # never reach it.
    _data_source(db, hostile.id, "properties/1/../../admin")

    assert _resolve_ga4_targets(db) == []


def test_legacy_hand_written_config_still_works(db: Session) -> None:
    """Any row inserted directly into project_ga4_configs keeps syncing."""
    project = _project(db, "Legacy")
    db.add(
        models.ProjectGA4Config(
            project_id=project.id, ga4_property_id="properties/555", is_active=True
        )
    )
    db.commit()

    targets = _resolve_ga4_targets(db)

    assert [(t.project_id, t.ga4_property_id) for t in targets] == [(project.id, "properties/555")]


def test_settings_mapping_wins_over_a_stale_legacy_row(db: Session) -> None:
    """The table with a UI is authoritative, so users can correct a stale value."""
    project = _project(db, "Both")
    _data_source(db, project.id, "properties/999")
    db.add(
        models.ProjectGA4Config(
            project_id=project.id, ga4_property_id="properties/111", is_active=True
        )
    )
    db.commit()

    targets = _resolve_ga4_targets(db)

    assert len(targets) == 1
    assert targets[0].ga4_property_id == "properties/999"


@pytest.mark.parametrize(
    "raw",
    ["", None, "properties/", "properties/abc", "../../etc/passwd", "properties/1:runReport"],
)
def test_normalizer_rejects_anything_that_is_not_digits(raw: str | None) -> None:
    assert _normalize_ga4_property_id(raw) is None


@pytest.mark.parametrize("raw", ["42", " 42 ", "properties/42"])
def test_normalizer_accepts_both_spellings(raw: str) -> None:
    assert _normalize_ga4_property_id(raw) == "properties/42"
