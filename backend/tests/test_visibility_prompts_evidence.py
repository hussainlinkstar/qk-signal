"""SIGV2-1010: AIO prompts-table evidence serialization.

Covers scan-linked vs scheduled measurement snapshots, canonical search-type
classification, presence semantics (citation / mention / measured absence /
unmeasured), server-side top-engine derivation, null-with-reason position,
who-wins competitor citations, per-run provenance, and foreign-project access.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from services.project_visibility_service import (
    PRESENCE_BRAND_MENTION,
    PRESENCE_DOMAIN_CITATION,
    PRESENCE_MEASURED_ABSENT,
    PRESENCE_UNMEASURED,
    REASON_MEASUREMENT_FAILED,
    REASON_NO_COMPLETED_MEASUREMENTS,
    REASON_NO_MEASUREMENT,
    REASON_ORDINAL_POSITION_NOT_RECORDED,
    REASON_PROXY_NOT_LIVE,
    REASON_TIED_PROVIDERS,
    MEASUREMENT_ORIGIN_SCAN,
    MEASUREMENT_ORIGIN_SCHEDULED,
)
from services.query_taxonomy import CANONICAL_SEARCH_TYPES

try:
    from main import app, get_current_user, get_db
except Exception:  # pragma: no cover
    app = None
    get_current_user = None
    get_db = None


NOW = datetime.now(timezone.utc)


# SIGV2-1216: Executive, because its roster is the only one holding every
# offered engine. Every fixture below records its cells on ``google``, which
# Specialist stopped measuring when the plan was repriced, and an engine
# outside the project's roster now contributes no cell to any surface. On
# Specialist these tests would be measuring that filter instead of the
# evidence, provenance and presence semantics they are about. The filter
# itself is pinned by ``tests/test_plan_unmeasured_engines.py``.
def _build_client(
    plan_type: str = "plan_executive",
) -> tuple[TestClient, object, models.User, models.Project]:
    if app is None or get_db is None or get_current_user is None:
        pytest.skip("main app import unavailable in this test runtime")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    user = models.User(
        email="prompts-evidence@example.com",
        hashed_password="x",
        role="user",
        credits=25,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{plan_type}",
            stripe_subscription_id=f"sub_{plan_type}",
            plan_type=plan_type,
            status="active",
        )
    )
    db.commit()

    workspace = models.Workspace(name="Evidence Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Northwind",
        domain_url="northwind.example",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    return TestClient(app), db, user, project


def _cleanup(db) -> None:
    if app is not None:
        app.dependency_overrides.clear()
    bind = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=bind)


def _add_query(
    db, project_id: int, query_text: str, providers: list[str]
) -> models.ProjectVisibilityQuery:
    query = models.ProjectVisibilityQuery(
        project_id=project_id,
        query_text=query_text,
        query_type="aeo",
        providers=providers,
        is_active=True,
    )
    db.add(query)
    db.commit()
    db.refresh(query)
    return query


def _add_batch(
    db,
    *,
    project_id: int | None,
    topic: str,
    provider: str,
    target_domain: str | None = "northwind.example",
    schedule_key: str = "202610040900",
    audit_job_id: str | None = None,
    status: str = "succeeded",
    score: float | None = 50.0,
    citations: list[str] | None = None,
    response_text: str = "answer text",
    engine_source: str = "openrouter_live",
    model: str = "openai/gpt-4o",
    served_from_cache: bool = False,
    attempt: int = 1,
    fallback_reason: str | None = None,
    created_at: datetime | None = None,
) -> models.VisibilityRunBatch:
    batch = models.VisibilityRunBatch(
        project_id=project_id,
        topic=topic,
        provider=provider,
        target_domain=target_domain,
        schedule_key=schedule_key,
        audit_job_id=audit_job_id,
        status=status,
        score=score,
        started_at=created_at or NOW,
        completed_at=created_at or NOW,
        created_at=created_at or NOW,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    valid = list(citations or [])
    raw_response = {
        "answer": response_text,
        "model": model,
        "engine_source": engine_source,
        "attempt": attempt,
        "measured_at": (created_at or NOW).isoformat(),
    }
    if served_from_cache:
        raw_response["served_from_cache"] = True
    if fallback_reason:
        raw_response["fallback_reason"] = fallback_reason
    run = models.VisibilityRun(
        batch_id=batch.id,
        topic=topic,
        provider=provider,
        target_domain=target_domain,
        prompt_template="buyer_recommendation",
        prompt=f"Recommend top providers for {topic} and cite authoritative references.",
        raw_response=raw_response,
        parsed_citations=valid,
        valid_citations=valid,
        score=score,
        status="succeeded" if status == "succeeded" else "failed",
        started_at=created_at or NOW,
        completed_at=created_at or NOW,
    )
    db.add(run)
    db.commit()
    db.refresh(batch)
    return batch


def _summary(client: TestClient, project_id: int, **params) -> dict:
    response = client.get(
        f"/api/v1/projects/{project_id}/monitoring/visibility-summary", params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_canonical_search_type_serialized_alongside_query_type() -> None:
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["google"])
        _add_query(db, project.id, "acme vs northwind", ["google"])
        _add_query(db, project.id, "payroll software pricing", ["google"])
        _add_query(db, project.id, "how to run payroll", ["google"])

        payload = _summary(client, project.id)
        rows = {row["query_text"]: row for row in payload["queries"]}

        # query_type stays the internal aeo/geo lane; search_type is the
        # canonical five-way taxonomy classified off the query text.
        assert all(row["query_type"] == "aeo" for row in rows.values())
        assert rows["acme vs northwind"]["search_type"] == "comparison"
        assert rows["payroll software pricing"]["search_type"] == "feature"
        assert rows["how to run payroll"]["search_type"] == "problem"
        assert rows["best payroll software"]["search_type"] == "category"
        for row in rows.values():
            assert row["search_type"] in CANONICAL_SEARCH_TYPES
    finally:
        _cleanup(db)


def test_scan_linked_snapshot_excludes_scheduled_measurements() -> None:
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["google"])
        scheduled = _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="google",
            schedule_key="202610050800",
            score=90.0,
            citations=["https://northwind.example/pricing"],
            created_at=NOW,
        )
        scan = _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="google",
            schedule_key="queued",
            audit_job_id="job-scan-1",
            score=40.0,
            citations=[],
            response_text="no mention of the target",
            created_at=NOW - timedelta(hours=1),
        )

        # Default view: the latest measurement wins regardless of origin, and
        # each cell identifies its real origin.
        payload = _summary(client, project.id)
        assert payload["audit_job_id"] is None
        cell = payload["queries"][0]["results"][0]
        assert cell["evidence"]["batch_id"] == scheduled.id
        assert cell["measurement_origin"] == MEASUREMENT_ORIGIN_SCHEDULED

        # Scan-scoped view: only the batches this audit job triggered.
        payload = _summary(client, project.id, audit_job_id="job-scan-1")
        assert payload["audit_job_id"] == "job-scan-1"
        cell = payload["queries"][0]["results"][0]
        assert cell["evidence"]["batch_id"] == scan.id
        assert cell["audit_job_id"] == "job-scan-1"
        assert cell["measurement_origin"] == MEASUREMENT_ORIGIN_SCAN

        # A different scan id sees no measurement at all, never the scheduled one.
        payload = _summary(client, project.id, audit_job_id="job-other")
        cell = payload["queries"][0]["results"][0]
        assert cell["status"] == "pending"
        assert cell["evidence"] is None
        assert cell["presence"]["state"] == PRESENCE_UNMEASURED
    finally:
        _cleanup(db)


def test_cell_provenance_surfaces_rendered_prompt_model_and_origin() -> None:
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["google"])
        batch = _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="google",
            citations=["https://northwind.example"],
            served_from_cache=True,
            attempt=2,
        )

        payload = _summary(client, project.id)
        cell = payload["queries"][0]["results"][0]
        assert cell["engine_source"] == "openrouter_live"
        assert cell["model"] == "openai/gpt-4o"
        evidence = cell["evidence"]
        assert evidence["batch_id"] == batch.id
        run = evidence["runs"][0]
        assert run["prompt_template"] == "buyer_recommendation"
        assert (
            run["prompt"]
            == "Recommend top providers for best payroll software and cite authoritative references."
        )
        assert run["model"] == "openai/gpt-4o"
        assert run["engine_source"] == "openrouter_live"
        assert run["served_from_cache"] is True
        assert run["attempt"] == 2
        assert run["measured_at"]
        # SIGV2-1313: a run that reached its engine carries no reason.
        assert run["fallback_reason"] is None
        assert evidence["run_ids"] == [run["run_id"]]
    finally:
        _cleanup(db)


def test_presence_semantics_distinguish_citation_mention_absent_unmeasured() -> None:
    client, db, _user, project = _build_client()
    try:
        _add_query(
            db,
            project.id,
            "best payroll software",
            ["google", "openai", "anthropic", "perplexity", "xai"],
        )
        # Cited: a valid citation matches the measured target domain.
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="google",
            citations=["https://northwind.example/pricing"],
        )
        # Brand mention: body text mentions the domain, no valid citation.
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="openai",
            citations=[],
            response_text="northwind.example is often suggested for payroll",
        )
        # Measured absent on a live engine: neither citation nor mention.
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="anthropic",
            citations=[],
            response_text="competitor tools dominate this category",
        )
        # Proxy-only absence: explicitly not a live-engine "no".
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="perplexity",
            citations=[],
            response_text="competitor tools dominate this category",
            engine_source="bedrock_proxy",
            model="bedrock/sonnet",
        )
        # Failed measurement: unmeasured, never absent.
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="xai",
            status="failed",
            score=None,
        )

        payload = _summary(client, project.id)
        cells = {c["provider"]: c for c in payload["queries"][0]["results"]}

        assert cells["google"]["presence"]["state"] == PRESENCE_DOMAIN_CITATION
        assert cells["google"]["presence"]["live_measured"] is True

        assert cells["openai"]["presence"]["state"] == PRESENCE_BRAND_MENTION

        absent = cells["anthropic"]["presence"]
        assert absent["state"] == PRESENCE_MEASURED_ABSENT
        assert absent["live_measured"] is True
        assert absent["reason"] == "no_evidence_in_measurement"

        proxy = cells["perplexity"]["presence"]
        assert proxy["state"] == PRESENCE_MEASURED_ABSENT
        assert proxy["live_measured"] is False
        assert proxy["reason"] == REASON_PROXY_NOT_LIVE
        assert cells["perplexity"]["engine_source"] == "bedrock_proxy"

        failed = cells["xai"]["presence"]
        assert failed["state"] == PRESENCE_UNMEASURED
        assert failed["reason"] == "measurement_failed"
    finally:
        _cleanup(db)


def test_top_engine_derived_server_side_and_null_on_tie() -> None:
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "q1 clear winner", ["google", "openai"])
        _add_batch(
            db,
            project_id=project.id,
            topic="q1 clear winner",
            provider="google",
            score=80.0,
            citations=["https://northwind.example"],
        )
        _add_batch(
            db,
            project_id=project.id,
            topic="q1 clear winner",
            provider="openai",
            score=30.0,
        )

        _add_query(db, project.id, "q2 tied", ["google", "openai"])
        for provider in ("google", "openai"):
            _add_batch(
                db,
                project_id=project.id,
                topic="q2 tied",
                provider=provider,
                score=55.0,
            )

        _add_query(db, project.id, "q3 unmeasured", ["google"])

        payload = _summary(client, project.id)
        rows = {row["query_text"]: row for row in payload["queries"]}

        top = rows["q1 clear winner"]["top_engine"]
        assert top["provider"] == "google"
        assert top["score"] == 80.0
        assert top["reason"] is None
        assert top["evidence"]["batch_id"]

        tied = rows["q2 tied"]["top_engine"]
        assert tied["provider"] is None
        assert tied["reason"] == REASON_TIED_PROVIDERS

        empty = rows["q3 unmeasured"]["top_engine"]
        assert empty["provider"] is None
        assert empty["reason"] == REASON_NO_COMPLETED_MEASUREMENTS
    finally:
        _cleanup(db)


def test_position_is_null_with_reason_never_invented() -> None:
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["google"])
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="google",
            citations=["https://northwind.example", "https://rival.example"],
        )

        payload = _summary(client, project.id)
        position = payload["queries"][0]["position"]
        assert position["value"] is None
        assert position["reason"] == REASON_ORDINAL_POSITION_NOT_RECORDED
    finally:
        _cleanup(db)


def test_who_wins_serializes_cited_domains_with_evidence() -> None:
    client, db, _user, project = _build_client()
    try:
        competitor = models.ProjectCompetitor(
            project_id=project.id,
            target_url="https://rival.example",
            normalized_domain="rival.example",
            display_name="Rival",
        )
        db.add(competitor)
        _add_query(db, project.id, "best payroll software", ["google"])
        batch = _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="google",
            citations=[
                "https://northwind.example",
                "https://rival.example/a",
                "https://rival.example/b",
                "https://other.org/page",
            ],
        )
        db.commit()

        payload = _summary(client, project.id)
        who_wins = payload["queries"][0]["who_wins"]
        domains = [entry["domain"] for entry in who_wins]
        # Target domain excluded; citation frequency orders, rival first.
        assert "northwind.example" not in domains
        assert domains[0] == "rival.example"
        rival = who_wins[0]
        assert rival["is_configured_competitor"] is True
        assert rival["citations"] == 2
        assert rival["batch_ids"] == [batch.id]
        assert rival["run_ids"] == [batch.runs[0].id]
        other = who_wins[1]
        assert other["domain"] == "other.org"
        assert other["is_configured_competitor"] is False
    finally:
        _cleanup(db)


def test_no_runs_yields_pending_cells_and_null_row_fields() -> None:
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["google", "openai"])

        payload = _summary(client, project.id)
        row = payload["queries"][0]
        assert all(cell["status"] == "pending" for cell in row["results"])
        assert all(cell["presence"]["reason"] == REASON_NO_MEASUREMENT for cell in row["results"])
        assert row["top_engine"]["reason"] == REASON_NO_COMPLETED_MEASUREMENTS
        assert row["position"]["value"] is None
        assert row["who_wins"] == []
    finally:
        _cleanup(db)


def test_partial_provider_failure_does_not_block_top_engine() -> None:
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["google", "openai"])
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="google",
            status="failed",
            score=None,
        )
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="openai",
            score=42.0,
        )

        payload = _summary(client, project.id)
        cells = {c["provider"]: c for c in payload["queries"][0]["results"]}
        assert cells["google"]["status"] == "failed"
        assert cells["google"]["presence"]["state"] == PRESENCE_UNMEASURED
        assert payload["queries"][0]["top_engine"]["provider"] == "openai"
    finally:
        _cleanup(db)


def test_foreign_project_access_refused() -> None:
    client, db, user, project = _build_client()
    try:
        foreign = models.User(
            email="foreign@example.com",
            hashed_password="x",
            role="user",
            credits=5,
            notifications_enabled=True,
        )
        db.add(foreign)
        db.commit()
        db.refresh(foreign)

        app.dependency_overrides[get_current_user] = lambda: foreign
        response = client.get(f"/api/v1/projects/{project.id}/monitoring/visibility-summary")
        assert response.status_code in {403, 404}
        # Evidence references stay scoped: the scan-linked view is refused too.
        response = client.get(
            f"/api/v1/projects/{project.id}/monitoring/visibility-summary",
            params={"audit_job_id": "job-scan-1"},
        )
        assert response.status_code in {403, 404}
    finally:
        _cleanup(db)


def test_end_to_end_trace_query_to_cell_evidence() -> None:
    """Sanitized end-to-end: configured query -> rendered prompt -> persisted
    run -> summary API -> table row, every column backed by a real field."""
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "acme vs northwind payroll", ["google"])
        _add_batch(
            db,
            project_id=project.id,
            topic="acme vs northwind payroll",
            provider="google",
            citations=["https://northwind.example", "https://rival.example/x"],
            engine_source="bedrock_proxy",
            model="bedrock/claude",
        )

        payload = _summary(client, project.id)
        row = payload["queries"][0]
        cell = row["results"][0]
        run = cell["evidence"]["runs"][0]

        # prompt -> type -> presence -> top engine -> who wins -> provenance
        assert row["query_text"] == "acme vs northwind payroll"
        assert row["search_type"] == "comparison"
        assert cell["presence"]["state"] == PRESENCE_DOMAIN_CITATION
        assert row["top_engine"]["provider"] == "google"
        assert any(e["domain"] == "rival.example" for e in row["who_wins"])
        assert run["prompt_template"] == "buyer_recommendation"
        assert "acme vs northwind payroll" in run["prompt"]
        assert run["model"] == "bedrock/claude"
        assert run["engine_source"] == "bedrock_proxy"
    finally:
        _cleanup(db)


def test_a_legacy_degraded_batch_whose_runs_all_failed_reads_as_failed() -> None:
    """Rows written before the writer stopped scoring total failures.

    Those batches are stored as ``degraded`` with ``score=0.0`` and are still
    in the database. Reading one as a completed measurement is what published
    a provider outage as a measured zero, so the reader classifies a batch
    whose every run failed as failed whatever its stored status says. No
    migration, and the stored row is left exactly as it is.
    """
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["openai"])
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="openai",
            status="degraded",
            score=0.0,
        )

        payload = _summary(client, project.id)
        cell = payload["queries"][0]["results"][0]

        assert cell["status"] == "failed"
        assert cell["score"] is None
        assert cell["presence"]["state"] == PRESENCE_UNMEASURED
        assert cell["presence"]["reason"] == REASON_MEASUREMENT_FAILED
        # The stored row is untouched, so the failure stays diagnosable.
        assert cell["batch_status"] == "degraded"
        # And nothing claims a measurement happened.
        assert payload["completed_checks"] == 0
        assert payload["visibility_score"] is None
    finally:
        _cleanup(db)


# ---------------------------------------------------------------------------
# Named in the answer without a link (Razvan, 9 Oct: report the state, leave
# the score alone).
# ---------------------------------------------------------------------------


def test_a_brand_named_without_a_link_is_a_mention_not_an_absence() -> None:
    """Being recommended by name is the normal shape of an AI answer.

    Scoring only ever looked for the domain string in the answer body and the
    brand name was never passed in, so "Northwind is the strongest option"
    measured identically to never appearing at all. That is the one signal
    customers are paying to track, reported as absence.
    """
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["openai"])
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="openai",
            score=12.0,
            citations=["https://rival.example/review"],
            response_text="For most teams Northwind is the strongest option on the market.",
        )

        payload = _summary(client, project.id)
        cell = payload["queries"][0]["results"][0]

        assert cell["presence"]["state"] == PRESENCE_BRAND_MENTION
        # The decision was explicitly to report the state and not move any
        # number: the composite is whatever the run scored.
        assert cell["score"] == 12.0
    finally:
        _cleanup(db)


def test_an_answer_that_never_names_the_brand_is_still_measured_absent() -> None:
    """The new state must not turn every absence into a mention."""
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["openai"])
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="openai",
            score=0.0,
            citations=["https://rival.example/review"],
            response_text="Rival Systems and Acme Payroll lead this category.",
        )

        payload = _summary(client, project.id)
        cell = payload["queries"][0]["results"][0]

        assert cell["presence"]["state"] == PRESENCE_MEASURED_ABSENT
    finally:
        _cleanup(db)


def test_the_brand_match_respects_word_boundaries() -> None:
    """A brand inside a longer word is not a mention.

    Without this, a short or common brand name would report a mention in any
    answer that happened to contain those letters, which is the same class of
    false positive as the bot registry matching "Googlebot" on a bare token.
    """
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["openai"])
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="openai",
            score=0.0,
            citations=[],
            response_text="Northwindsurfing Club publishes an unrelated newsletter.",
        )

        payload = _summary(client, project.id)
        cell = payload["queries"][0]["results"][0]

        assert cell["presence"]["state"] == PRESENCE_MEASURED_ABSENT
    finally:
        _cleanup(db)


def test_a_failed_batch_is_never_reported_as_a_brand_mention() -> None:
    """Failure outranks the new state: nothing was measured."""
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["openai"])
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="openai",
            status="failed",
            score=None,
            response_text="Northwind is the strongest option on the market.",
        )

        payload = _summary(client, project.id)
        cell = payload["queries"][0]["results"][0]

        assert cell["status"] == "failed"
        assert cell["presence"]["state"] == PRESENCE_UNMEASURED
    finally:
        _cleanup(db)


# ---------------------------------------------------------------------------
# Self-review of the failure fixes: nulling the score is not enough on its
# own, because a failed cell reaches two more aggregates.
# ---------------------------------------------------------------------------


def test_a_failed_cell_contributes_no_breakdown_to_the_aggregate() -> None:
    """The breakdown has to go with the score.

    Nulling the score but keeping `score_breakdown` left a failed batch's
    per-factor numbers feeding the project's aggregate breakdown: the same
    defect one level down, a failure contributing to a published average.
    """
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["openai"])
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="openai",
            status="degraded",
            score=0.0,
        )

        payload = _summary(client, project.id)
        cell = payload["queries"][0]["results"][0]

        assert cell["status"] == "failed"
        assert cell["score"] is None
        assert cell["score_breakdown"] is None
        assert payload["score_breakdown"] is None
    finally:
        _cleanup(db)


def test_a_failed_attempt_does_not_advance_the_freshness_clock() -> None:
    """A failure has a timestamp but carries no new data.

    Letting it advance `last_updated_at` told the customer the measurement
    was taken moments ago when nothing had been measured at all, which reads
    as fresh evidence of absence. The last successful measurement is what the
    clock must report.
    """
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["google", "openai"])
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="google",
            score=42.0,
            citations=["https://northwind.example/pricing"],
            created_at=NOW - timedelta(days=3),
        )
        # A newer attempt that failed outright.
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="openai",
            status="failed",
            score=None,
            created_at=NOW,
        )

        payload = _summary(client, project.id)
        row = payload["queries"][0]

        # The clock reports the successful measurement, three days old, not
        # the failure that happened just now.
        assert payload["last_updated_at"] is not None
        assert payload["last_updated_at"].startswith((NOW - timedelta(days=3)).date().isoformat())
        assert row["last_checked_at"].startswith((NOW - timedelta(days=3)).date().isoformat())

        # The attempt itself is still visible on its own cell, so the failure
        # stays diagnosable.
        failed_cell = next(c for c in row["results"] if c["provider"] == "openai")
        assert failed_cell["status"] == "failed"
        assert failed_cell["last_checked_at"] is not None
    finally:
        _cleanup(db)


def test_a_succeeded_run_that_said_nothing_is_not_a_measured_zero() -> None:
    """The reported symptom: every card reads 0 and says Measured.

    A live reasoning engine can be billed in full and return nothing
    (SIGV2-1269). The run is written `succeeded` because the HTTP call
    worked, the score comes out 0 because no text mentioned the brand, and
    the surface reports a measured zero for an answer the engine never gave.

    Six rows of exactly this shape on the preprod project made "Why AI
    recommends your website" read 0 on all five cards. The first version of
    `_batch_measured_nothing` missed them: it tested run *status*, and the
    status was `succeeded`.
    """
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["openai"])
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="openai",
            status="succeeded",
            score=0.0,
            response_text="",
            citations=[],
        )

        payload = _summary(client, project.id)
        cell = payload["queries"][0]["results"][0]

        assert cell["status"] == "failed"
        assert cell["score"] is None
        assert payload["completed_checks"] == 0
    finally:
        _cleanup(db)


def test_citations_with_no_prose_still_count_as_an_answer() -> None:
    """An engine may return sources and no narrative.

    That is still a statement about where the brand appears, so it must stay
    a real measurement rather than being discarded with the silent ones.
    """
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["openai"])
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="openai",
            status="succeeded",
            score=40.0,
            response_text="",
            citations=["https://northwind.example/pricing"],
        )

        payload = _summary(client, project.id)
        cell = payload["queries"][0]["results"][0]

        assert cell["status"] == "cited"
        assert cell["score"] == 40.0
    finally:
        _cleanup(db)


def test_a_run_with_no_stored_response_keeps_its_existing_meaning() -> None:
    """Absent is not empty.

    The worker always writes a response on success, so a run without one is
    an old or synthetic row rather than an engine that said nothing. Treating
    it as a non-measurement would silently rewrite the score of every
    historical cell shaped that way, which is a change to every customer's
    number dressed up as a bug fix. Only a response that is present and
    states an empty answer is rejected.
    """
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["openai"])
        batch = _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="openai",
            status="succeeded",
            score=0.0,
            citations=[],
        )
        # Strip the response entirely, leaving a successful run that simply
        # never recorded what came back.
        for run in batch.runs:
            run.raw_response = None
        db.commit()

        payload = _summary(client, project.id)
        cell = payload["queries"][0]["results"][0]

        assert cell["status"] == "not_cited"
        assert cell["score"] == 0.0
        assert payload["completed_checks"] == 1
    finally:
        _cleanup(db)


def test_run_evidence_names_why_a_cell_fell_back_to_the_proxy() -> None:
    """SIGV2-1313: SIGV2-1300's reason has to leave the database.

    SIGV2-1299 marks a fallback cell in the UI but could not say which of the
    four reasons it was, because the field was never serialised.
    """
    client, db, _user, project = _build_client()
    try:
        _add_query(db, project.id, "best payroll software", ["google"])
        _add_batch(
            db,
            project_id=project.id,
            topic="best payroll software",
            provider="google",
            citations=["https://northwind.example"],
            engine_source="bedrock_proxy",
            model="qwen.qwen3-235b-a22b-2507-v1:0",
            fallback_reason="live_measurement_disabled",
        )

        payload = _summary(client, project.id)
        run = payload["queries"][0]["results"][0]["evidence"]["runs"][0]
        assert run["engine_source"] == "bedrock_proxy"
        assert run["fallback_reason"] == "live_measurement_disabled"
    finally:
        _cleanup(db)
