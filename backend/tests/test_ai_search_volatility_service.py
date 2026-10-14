from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SSM_ENABLED", "false")

import models
from database import Base
from services.ai_search_volatility_service import AISearchVolatilityService


def _build_db() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup(db: Session, engine) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_rebuild_snapshots_and_public_payload() -> None:
    db, engine = _build_db()
    try:
        seed = models.GlobalVolatilitySeedQuery(
            query_text="best llm observability platforms",
            normalized_query="best llm observability platforms",
            industry="tech",
            priority_weight=1.0,
            is_active=True,
            source="test",
            schema_version="1",
        )
        db.add(seed)
        db.flush()

        # Use dates relative to "today" so the public dashboard's trailing-window
        # query (build_industry_matrix windows to today-N..today) remains
        # deterministic regardless of the wall clock.
        latest_run_date = datetime.now(timezone.utc).date()
        previous_run_date = latest_run_date - timedelta(days=1)

        db.add_all(
            [
                models.DailySeedQueryRun(
                    seed_query_id=seed.id,
                    provider="google",
                    run_date=previous_run_date,
                    answer_text="Platform A and Platform B are recommended.",
                    citation_domains_json=["platform-a.com", "platform-b.com"],
                    citations_count=2,
                    answer_format="paragraph",
                    schema_version="1",
                ),
                models.DailySeedQueryRun(
                    seed_query_id=seed.id,
                    provider="google",
                    run_date=latest_run_date,
                    answer_text="1. Platform C. 2. Platform B.",
                    citation_domains_json=["platform-c.com", "platform-b.com"],
                    citations_count=2,
                    answer_format="list",
                    schema_version="1",
                ),
            ]
        )
        db.commit()

        service = AISearchVolatilityService(db)
        written = service.rebuild_snapshots_for_date(run_date=latest_run_date)
        db.commit()

        assert written >= 1
        summary = service.build_summary(days=30, provider="all")
        assert summary["no_data"] is False
        assert summary["volatility_score"] is not None
        assert summary["compared_queries"] >= 1
        assert summary["weather_label"] in {"steady", "breezy", "turbulent", "stormy", "calm"}
        assert isinstance(summary["top_winners"], list)

        trends = service.build_trends(days=30, provider="all")
        assert trends["provider"] == "all"
        assert len(trends["points"]) == 30

        public_payload = service.build_public_dashboard(days=30, provider="google")
        assert public_payload["available_providers"] == ["google"]
        assert public_payload["summary"]["provider"] == "google"
        assert public_payload["industry_matrix"]["provider"] == "google"
        assert len(public_payload["industry_matrix"]["points"]) == 1
        assert public_payload["industry_matrix"]["points"][0]["industry"] == "tech"
        assert public_payload["industry_matrix"]["points"][0]["moving_queries"] == [
            "best llm observability platforms"
        ]
        assert public_payload["citation_ledger"]["provider"] == "google"
        assert len(public_payload["citation_ledger"]["rows"]) == 2
        assert public_payload["citation_ledger"]["rows"][0]["trend"] == [0, 0, 0, 0, 0, 0, 1]
        assert {row["domain"] for row in public_payload["citation_ledger"]["rows"]} == {
            "platform-a.com",
            "platform-c.com",
        }
    finally:
        _cleanup(db, engine)


def test_all_provider_snapshot_aggregates_provider_specific_pairs() -> None:
    db, engine = _build_db()
    try:
        seed = models.GlobalVolatilitySeedQuery(
            query_text="best llm observability platforms",
            normalized_query="best llm observability platforms",
            industry="tech",
            priority_weight=1.0,
            is_active=True,
            source="test",
            schema_version="1",
        )
        db.add(seed)
        db.flush()

        db.add_all(
            [
                models.DailySeedQueryRun(
                    seed_query_id=seed.id,
                    provider="google",
                    run_date=date(2026, 3, 4),
                    answer_text="Platform A and Platform B are recommended.",
                    citation_domains_json=["platform-a.com", "platform-b.com"],
                    citations_count=2,
                    answer_format="paragraph",
                    schema_version="1",
                ),
                models.DailySeedQueryRun(
                    seed_query_id=seed.id,
                    provider="google",
                    run_date=date(2026, 3, 5),
                    answer_text="1. Platform C. 2. Platform B.",
                    citation_domains_json=["platform-c.com", "platform-b.com"],
                    citations_count=2,
                    answer_format="list",
                    schema_version="1",
                ),
                models.DailySeedQueryRun(
                    seed_query_id=seed.id,
                    provider="openai",
                    run_date=date(2026, 3, 4),
                    answer_text="Platform X and Platform B are recommended.",
                    citation_domains_json=["platform-x.com", "platform-b.com"],
                    citations_count=2,
                    answer_format="paragraph",
                    schema_version="1",
                ),
                models.DailySeedQueryRun(
                    seed_query_id=seed.id,
                    provider="openai",
                    run_date=date(2026, 3, 5),
                    answer_text="1. Platform Y. 2. Platform B.",
                    citation_domains_json=["platform-y.com", "platform-b.com"],
                    citations_count=2,
                    answer_format="list",
                    schema_version="1",
                ),
            ]
        )
        db.commit()

        service = AISearchVolatilityService(db)
        written = service.rebuild_snapshots_for_date(run_date=date(2026, 3, 5))
        db.commit()

        assert written >= 3
        summary = service.build_summary(days=30, provider="all")
        assert summary["provider"] == "all"
        assert summary["compared_queries"] == 2
        assert {row["domain"] for row in summary["top_winners"]} == {
            "platform-c.com",
            "platform-y.com",
        }
        assert {row["domain"] for row in summary["top_losers"]} == {
            "platform-a.com",
            "platform-x.com",
        }

        ledger = service.build_citation_ledger(days=30, provider="all")
        assert {row["domain"] for row in ledger["rows"]} == {
            "platform-a.com",
            "platform-c.com",
            "platform-x.com",
            "platform-y.com",
        }
        assert all(len(row["trend"]) == 7 for row in ledger["rows"])
    finally:
        _cleanup(db, engine)
