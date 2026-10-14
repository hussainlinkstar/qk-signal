"""Constant-time comparison, expiry and rotation for audit share tokens.

SIGV2-1250: the share check compared ``audit.share_token != token`` with a
plain string comparison, and a token was minted once and then lived forever
with no expiry, rotation or revocation path.

``services.audit_share_token_service`` owns all three concerns so the decision
is testable on its own and identical wherever it is enforced. The migration is
checked as a static contract, never executed (AGENTS.md 4.2).
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISABLE_TRACING", "1")

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from core.config import settings
from database import Base
from routers import api_router
from services import audit_share_token_service as share_tokens

NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20261017_010000_add_audit_share_token_expires_at.py"
)


def _audit(token=None, expires_at=None):
    """A stand-in for the Audit row: the service only touches two columns."""
    return SimpleNamespace(share_token=token, share_token_expires_at=expires_at)


def _NOW_PLUS_A_DAY() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=1)


# ---------------------------------------------------------------------------
# constant-time comparison
# ---------------------------------------------------------------------------


def test_matching_token_is_accepted():
    audit = _audit("a" * 32, NOW + timedelta(days=1))
    assert share_tokens.share_token_matches(audit, "a" * 32, now=NOW) is True


def test_wrong_token_of_the_same_length_is_rejected():
    audit = _audit("a" * 32, NOW + timedelta(days=1))
    assert share_tokens.share_token_matches(audit, "a" * 31 + "b", now=NOW) is False


def test_comparison_goes_through_secrets_compare_digest():
    audit = _audit("a" * 32, NOW + timedelta(days=1))

    with patch(
        "services.audit_share_token_service.secrets.compare_digest",
        wraps=share_tokens.secrets.compare_digest,
    ) as spy:
        assert share_tokens.share_token_matches(audit, "a" * 32, now=NOW) is True

    spy.assert_called_once()


def test_unshared_audit_rejects_every_token():
    assert share_tokens.share_token_matches(_audit(None), "a" * 32, now=NOW) is False
    assert share_tokens.share_token_matches(_audit(""), "", now=NOW) is False


def test_empty_and_non_ascii_candidates_are_rejected_without_raising():
    audit = _audit("a" * 32, NOW + timedelta(days=1))
    assert share_tokens.share_token_matches(audit, "", now=NOW) is False
    assert share_tokens.share_token_matches(audit, None, now=NOW) is False
    assert share_tokens.share_token_matches(audit, "tokén-with-accents", now=NOW) is False


# ---------------------------------------------------------------------------
# expiry
# ---------------------------------------------------------------------------


def test_expired_token_is_rejected_even_though_it_matches():
    audit = _audit("a" * 32, NOW - timedelta(seconds=1))
    assert share_tokens.is_share_token_expired(audit, now=NOW) is True
    assert share_tokens.share_token_matches(audit, "a" * 32, now=NOW) is False


def test_token_expiring_later_is_still_valid():
    audit = _audit("a" * 32, NOW + timedelta(seconds=1))
    assert share_tokens.is_share_token_expired(audit, now=NOW) is False
    assert share_tokens.share_token_matches(audit, "a" * 32, now=NOW) is True


def test_legacy_token_without_an_expiry_never_expires():
    """A token minted before this change has NULL expires_at and keeps working."""
    audit = _audit("a" * 32, None)
    assert share_tokens.is_share_token_expired(audit, now=NOW) is False
    assert share_tokens.share_token_matches(audit, "a" * 32, now=NOW) is True


def test_naive_expiry_timestamp_is_read_as_utc():
    audit = _audit("a" * 32, (NOW - timedelta(days=1)).replace(tzinfo=None))
    assert share_tokens.is_share_token_expired(audit, now=NOW) is True


# ---------------------------------------------------------------------------
# issuing
# ---------------------------------------------------------------------------


def test_issuing_on_an_unshared_audit_mints_a_token_with_an_expiry():
    audit = _audit()
    token = share_tokens.issue_share_token(audit, now=NOW)

    assert token == audit.share_token
    assert re.fullmatch(r"[0-9a-f]{32}", token)
    assert audit.share_token_expires_at == NOW + timedelta(days=settings.AUDIT_SHARE_TOKEN_TTL_DAYS)


def test_issuing_twice_returns_the_same_valid_token():
    audit = _audit("a" * 32, NOW + timedelta(days=5))
    assert share_tokens.issue_share_token(audit, now=NOW) == "a" * 32
    assert audit.share_token_expires_at == NOW + timedelta(days=5)


def test_issuing_replaces_an_expired_token():
    audit = _audit("a" * 32, NOW - timedelta(days=1))
    token = share_tokens.issue_share_token(audit, now=NOW)

    assert token != "a" * 32
    assert share_tokens.share_token_matches(audit, "a" * 32, now=NOW) is False
    assert share_tokens.share_token_matches(audit, token, now=NOW) is True


def test_issuing_adds_an_expiry_to_a_legacy_token_only_when_rotated():
    """A legacy token is left exactly as it is, expiry included (still NULL)."""
    audit = _audit("a" * 32, None)
    assert share_tokens.issue_share_token(audit, now=NOW) == "a" * 32
    assert audit.share_token_expires_at is None


def test_ttl_is_configurable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "AUDIT_SHARE_TOKEN_TTL_DAYS", 3, raising=False)
    audit = _audit()
    share_tokens.issue_share_token(audit, now=NOW)
    assert audit.share_token_expires_at == NOW + timedelta(days=3)


def test_default_ttl_is_thirty_days():
    assert settings.AUDIT_SHARE_TOKEN_TTL_DAYS == 30


def test_minted_tokens_are_unique_and_128_bit():
    tokens = {share_tokens.new_share_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(re.fullmatch(r"[0-9a-f]{32}", token) for token in tokens)


# ---------------------------------------------------------------------------
# rotation
# ---------------------------------------------------------------------------


def test_rotation_invalidates_the_previous_token():
    audit = _audit("a" * 32, NOW + timedelta(days=10))
    rotated = share_tokens.rotate_share_token(audit, now=NOW)

    assert rotated != "a" * 32
    assert share_tokens.share_token_matches(audit, "a" * 32, now=NOW) is False
    assert share_tokens.share_token_matches(audit, rotated, now=NOW) is True
    assert audit.share_token_expires_at == NOW + timedelta(days=settings.AUDIT_SHARE_TOKEN_TTL_DAYS)


def test_rotation_also_works_on_a_legacy_token_and_gives_it_an_expiry():
    audit = _audit("a" * 32, None)
    rotated = share_tokens.rotate_share_token(audit, now=NOW)

    assert rotated != "a" * 32
    assert audit.share_token_expires_at is not None


# ---------------------------------------------------------------------------
# model and migration
# ---------------------------------------------------------------------------


def test_audit_model_carries_a_nullable_share_token_expiry():
    column = models.Audit.__table__.columns["share_token_expires_at"]
    assert column.nullable is True
    assert column.server_default is None


def test_migration_chains_onto_the_previous_head():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert re.search(r'^revision\s*=\s*"20261017_010000"', source, flags=re.MULTILINE)
    assert re.search(r'^down_revision\s*=\s*"20261016_010000"', source, flags=re.MULTILINE)


def test_migration_history_does_not_branch():
    alembic_config = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    script_directory = ScriptDirectory.from_config(alembic_config)

    heads = script_directory.get_heads()
    assert len(heads) == 1, heads
    ancestors = {
        script_revision.revision
        for script_revision in script_directory.iterate_revisions(heads[0], None, inclusive=True)
    }
    assert "20261017_010000" in ancestors


def test_migration_adds_one_nullable_column_and_nothing_else():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]

    assert 'sa.Column("share_token_expires_at", sa.DateTime(timezone=True), nullable=True)' in (
        upgrade
    )
    assert upgrade.count("add_column") == 1

    lowered = upgrade.lower()
    for forbidden in (
        "drop_column",
        "drop_table",
        "drop table",
        "alter_column",
        "set not null",
        "nullable=false",
        "truncate",
        "delete from",
        "update ",
    ):
        assert forbidden not in lowered, forbidden


# ---------------------------------------------------------------------------
# the endpoints that actually enforce it
# ---------------------------------------------------------------------------
#
# The service above is only worth anything if the two public share endpoints
# go through it. These tests call the router functions directly against a
# real SQLite-backed session, so a regression that re-introduces
# ``audit.share_token != token`` in the router fails here, not only in review.


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _persisted_audit(db: Session, *, token=None, expires_at=None, report=None) -> models.Audit:
    user = models.User(email="owner@example.com", hashed_password="x", role="user", credits=5)
    db.add(user)
    db.flush()
    audit = models.Audit(
        user_id=user.id,
        url="https://example.com",
        geo_score=70.0,
        seo_score=80.0,
        aeo_score=75.0,
        full_report=report,
        share_token=token,
        share_token_expires_at=expires_at,
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


@pytest.fixture
def db() -> Session:
    session = _session()
    try:
        yield session
    finally:
        engine = session.get_bind()
        session.close()
        Base.metadata.drop_all(bind=engine)


def _read_shared(db: Session, audit: models.Audit, token):
    return api_router.get_shared_audit_record(audit_id=audit.id, token=token, db=db)


def test_shared_endpoint_rejects_a_wrong_token(db: Session):
    audit = _persisted_audit(db, token="a" * 32, expires_at=_NOW_PLUS_A_DAY())

    with pytest.raises(HTTPException) as raised:
        _read_shared(db, audit, "a" * 31 + "b")

    assert raised.value.status_code == 403


def test_shared_endpoint_rejects_an_expired_token(db: Session):
    """The deadline is enforced on read, not merely written at mint time."""
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    audit = _persisted_audit(db, token="a" * 32, expires_at=past)

    with pytest.raises(HTTPException) as raised:
        _read_shared(db, audit, "a" * 32)

    assert raised.value.status_code == 403


def test_shared_endpoint_accepts_a_valid_token(db: Session):
    audit = _persisted_audit(db, token="a" * 32, expires_at=_NOW_PLUS_A_DAY())

    # Past the token gate: the 404 is the missing report, not a rejected token.
    with pytest.raises(HTTPException) as raised:
        _read_shared(db, audit, "a" * 32)

    assert raised.value.status_code == 404


def test_shared_endpoint_still_accepts_a_legacy_token_without_an_expiry(db: Session):
    audit = _persisted_audit(db, token="a" * 32, expires_at=None)

    with pytest.raises(HTTPException) as raised:
        _read_shared(db, audit, "a" * 32)

    assert raised.value.status_code == 404


def test_shared_endpoint_compares_through_the_constant_time_service(db: Session):
    audit = _persisted_audit(db, token="a" * 32, expires_at=_NOW_PLUS_A_DAY())

    with patch(
        "routers.api_router.audit_share_tokens.share_token_matches",
        wraps=share_tokens.share_token_matches,
    ) as spy:
        with pytest.raises(HTTPException):
            _read_shared(db, audit, "a" * 32)

    spy.assert_called_once()


def test_create_share_link_mints_a_token_with_a_deadline(db: Session):
    audit = _persisted_audit(db)
    user = db.query(models.User).one()

    response = api_router.create_audit_share_link(audit_id=audit.id, user=user, db=db)

    db.refresh(audit)
    assert response["share_token"] == audit.share_token
    assert re.fullmatch(r"[0-9a-f]{32}", audit.share_token)
    assert audit.share_token_expires_at is not None
    assert "expires_at" in response


def test_create_share_link_is_idempotent_while_the_token_is_valid(db: Session):
    audit = _persisted_audit(db, token="a" * 32, expires_at=_NOW_PLUS_A_DAY())
    user = db.query(models.User).one()

    response = api_router.create_audit_share_link(audit_id=audit.id, user=user, db=db)

    assert response["share_token"] == "a" * 32


def test_create_share_link_rotates_an_expired_token(db: Session):
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    audit = _persisted_audit(db, token="a" * 32, expires_at=past)
    user = db.query(models.User).one()

    response = api_router.create_audit_share_link(audit_id=audit.id, user=user, db=db)

    db.refresh(audit)
    assert response["share_token"] != "a" * 32
    assert audit.share_token == response["share_token"]
    assert share_tokens.share_token_matches(audit, "a" * 32) is False


def test_router_does_not_compare_share_tokens_by_hand():
    """Guard against the original defect creeping back into the router."""
    source = (BACKEND_ROOT / "routers" / "api_router.py").read_text(encoding="utf-8")
    assert "audit.share_token != token" not in source
