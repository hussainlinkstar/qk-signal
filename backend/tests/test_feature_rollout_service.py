from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
from database import Base
from services.feature_rollout_service import (
    get_feature_rollout_state,
    is_actor_in_feature_rollout,
    upsert_feature_rollout,
)

_TEST_KEY = "test_feature"
_TEST_DESCRIPTION = "A generic test feature flag."


def _build_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return engine, testing_session()


def test_rollout_uses_enabled_default_when_no_flag_exists() -> None:
    engine, db = _build_db()

    try:
        state = get_feature_rollout_state(
            db,
            key=_TEST_KEY,
            default_enabled=True,
            default_rollout_percentage=100,
            default_description=_TEST_DESCRIPTION,
        )

        assert state.key == _TEST_KEY
        assert state.is_enabled is True
        assert state.rollout_percentage == 100
        assert state.source == "default"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_rollout_blocks_actor_when_flag_disabled() -> None:
    engine, db = _build_db()

    try:
        upsert_feature_rollout(
            db,
            key=_TEST_KEY,
            description=_TEST_DESCRIPTION,
            is_enabled=False,
            rollout_percentage=100,
        )
        db.commit()

        assert (
            is_actor_in_feature_rollout(
                db,
                key=_TEST_KEY,
                actor_key="42",
                default_enabled=True,
                default_rollout_percentage=100,
                default_description=_TEST_DESCRIPTION,
            )
            is False
        )
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_rollout_blocks_actor_when_rollout_percentage_is_zero() -> None:
    engine, db = _build_db()

    try:
        upsert_feature_rollout(
            db,
            key=_TEST_KEY,
            description=_TEST_DESCRIPTION,
            is_enabled=True,
            rollout_percentage=0,
        )
        db.commit()

        assert (
            is_actor_in_feature_rollout(
                db,
                key=_TEST_KEY,
                actor_key="42",
                default_enabled=True,
                default_rollout_percentage=100,
                default_description=_TEST_DESCRIPTION,
            )
            is False
        )
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
