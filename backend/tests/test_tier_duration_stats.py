"""Per-tier scan duration aggregates derived from recorded runs (SIGV2-1177).

The thing under test is not really "does it compute a quartile". It is the set
of promises the product makes when it prints a duration:

* the figure comes from recorded runs, never from a constant;
* below the minimum sample size there is **no figure at all**, not a zero and
  not a placeholder;
* a failed, cancelled, unfinished or machine-paced run is not a scan duration;
* the published numbers are the statistic the copy claims they are.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from services import tier_duration_stats_service as service

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    user = models.User(email="durations@example.com", hashed_password="x", role="user")
    session.add(user)
    session.commit()
    session.refresh(user)

    workspace = models.Workspace(name="Durations", owner_id=user.id)
    session.add(workspace)
    session.commit()
    session.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Durations",
        domain_url="https://example.com",
        language="en",
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    session.info["user_id"] = user.id
    session.info["project_id"] = project.id
    try:
        yield session
    finally:
        session.close()


def _add_job(
    db,
    *,
    tier: str,
    duration_seconds: float,
    status: str = "succeeded",
    completed_days_ago: float = 1.0,
    sitemap_crawl_job_id: str | None = None,
    scan_origin: str | None = None,
    started_at: datetime | None = -1,  # sentinel: derive from the duration
    completed_at: datetime | None = -1,
) -> models.AuditJob:
    completed = NOW - timedelta(days=completed_days_ago)
    started = completed - timedelta(seconds=duration_seconds)
    job = models.AuditJob(
        id=str(uuid.uuid4()),
        user_id=db.info["user_id"],
        status=status,
        url="https://example.com",
        audit_target_type=models.AuditTargetType.WEBSITE,
        tier=tier,
        started_at=started if started_at == -1 else started_at,
        completed_at=completed if completed_at == -1 else completed_at,
        sitemap_crawl_job_id=sitemap_crawl_job_id,
        scan_origin=scan_origin,
    )
    db.add(job)
    db.commit()
    return job


def _seed(
    db, *, tier: str, durations: list[float], completed_days_ago: float = 1.0, **kwargs
) -> None:
    for index, seconds in enumerate(durations):
        _add_job(
            db,
            tier=tier,
            duration_seconds=seconds,
            completed_days_ago=completed_days_ago + index * 0.01,
            **kwargs,
        )


def _recompute(db) -> dict[str, dict[str, object]]:
    summary = service.recompute_tier_duration_stats(db, now=NOW)
    db.commit()
    return summary


# ── The figure is measured, and it is the statistic the copy claims ──────────


class TestPublishedFigure:
    def test_publishes_the_interquartile_range_of_recorded_runs(self, db):
        # 20 runs: ten at 4 minutes, ten at 12. p25 lands inside the lower
        # cluster and p75 inside the upper one, so the published range is
        # 4..12 minutes and comes from these rows alone.
        _seed(db, tier="smart", durations=[240.0] * 10 + [720.0] * 10)
        _recompute(db)

        published = service.get_published_tier_durations(db, now=NOW)

        assert set(published) == {"smart"}
        figure = published["smart"]
        assert figure.sample_size == 20
        assert (figure.low_minutes, figure.high_minutes) == (4, 12)
        assert figure.window_days == service.WINDOW_DAYS

    def test_the_stored_quartiles_are_what_the_rows_say(self, db):
        # 20 evenly spaced runs from 1 to 20 minutes. Inclusive quartiles of
        # 60..1200 step 60 are p25=5.75min, p50=10.5min, p75=15.25min.
        _seed(db, tier="fast", durations=[60.0 * n for n in range(1, 21)])
        _recompute(db)

        row = db.query(models.AuditTierDurationStat).filter_by(tier="fast").one()
        assert row.p25_seconds == pytest.approx(345.0)
        assert row.p50_seconds == pytest.approx(630.0)
        assert row.p75_seconds == pytest.approx(915.0)

        figure = service.get_published_tier_durations(db, now=NOW)["fast"]
        # Rounded outward, so the published claim is a superset of the measured
        # interval: floor(5.75)=5 and ceil(15.25)=16.
        assert (figure.low_minutes, figure.high_minutes) == (5, 16)
        assert figure.median_minutes == 11

    def test_the_published_range_brackets_the_median(self, db):
        _seed(db, tier="deep_judgment", durations=[600.0 + n * 30 for n in range(24)])
        _recompute(db)

        figure = service.get_published_tier_durations(db, now=NOW)["deep_judgment"]
        assert figure.low_minutes <= figure.median_minutes <= figure.high_minutes

    def test_the_phrase_states_a_range_when_the_value_is_a_range(self, db):
        _seed(db, tier="smart", durations=[240.0] * 10 + [720.0] * 10)
        _recompute(db)
        figure = service.get_published_tier_durations(db, now=NOW)["smart"]

        phrase = service.format_duration_phrase(figure)

        # The copy must claim exactly what was computed: the middle half of a
        # named number of runs, as a range.
        assert phrase == "half of the last 20 scans finished in 4 to 12 minutes"

    def test_a_degenerate_range_is_worded_as_a_ceiling_not_a_promise(self, db):
        # Every run the same length: the quartiles collapse onto one minute, so
        # there is no range to state and "within" is the only true wording.
        _seed(db, tier="fast", durations=[300.0] * 20)
        _recompute(db)
        figure = service.get_published_tier_durations(db, now=NOW)["fast"]

        assert figure.low_minutes == figure.high_minutes == 5
        assert service.format_duration_phrase(figure) == (
            "half of the last 20 scans finished within 5 minutes"
        )


# ── Below the threshold the product says nothing ─────────────────────────────


class TestMinimumSampleSize:
    def test_publishes_nothing_below_the_threshold(self, db):
        _seed(db, tier="smart", durations=[600.0] * (service.MIN_SAMPLE_SIZE - 1))
        summary = _recompute(db)

        assert summary["smart"] == {
            "sample_size": service.MIN_SAMPLE_SIZE - 1,
            "published": False,
        }
        assert service.get_published_tier_durations(db, now=NOW) == {}

    def test_the_quartiles_are_not_even_stored_below_the_threshold(self, db):
        _seed(db, tier="smart", durations=[600.0] * 3)
        _recompute(db)

        row = db.query(models.AuditTierDurationStat).filter_by(tier="smart").one()
        # The real sample size is kept so an operator can see the distance to
        # publishable, but no figure exists to be served by mistake.
        assert row.sample_size == 3
        assert (row.p25_seconds, row.p50_seconds, row.p75_seconds) == (None, None, None)

    def test_publishes_exactly_at_the_threshold(self, db):
        _seed(db, tier="smart", durations=[600.0] * service.MIN_SAMPLE_SIZE)
        _recompute(db)

        assert "smart" in service.get_published_tier_durations(db, now=NOW)

    def test_an_empty_table_publishes_nothing(self, db):
        assert service.get_published_tier_durations(db, now=NOW) == {}

    def test_no_recorded_run_means_no_row_content_and_no_figure(self, db):
        summary = _recompute(db)

        assert all(entry["sample_size"] == 0 for entry in summary.values())
        assert all(entry["published"] is False for entry in summary.values())
        assert service.get_published_tier_durations(db, now=NOW) == {}

    def test_one_tier_publishing_does_not_publish_another(self, db):
        _seed(db, tier="fast", durations=[120.0 + n for n in range(service.MIN_SAMPLE_SIZE)])
        _seed(db, tier="smart", durations=[900.0] * 4)
        _recompute(db)

        published = service.get_published_tier_durations(db, now=NOW)
        assert set(published) == {"fast"}

    def test_a_stale_aggregate_is_not_served(self, db):
        _seed(db, tier="fast", durations=[300.0] * service.MIN_SAMPLE_SIZE)
        _recompute(db)
        assert "fast" in service.get_published_tier_durations(db, now=NOW)

        # The sweep runs hourly, so a row this old means it stopped running.
        # A frozen figure from an unknown pipeline state is not served.
        later = NOW + timedelta(days=service.MAX_STAT_AGE_DAYS, seconds=1)
        assert service.get_published_tier_durations(db, now=later) == {}


# ── What is not a scan duration ──────────────────────────────────────────────


class TestExclusions:
    @pytest.mark.parametrize("status", ["failed", "cancelled", "queued", "running"])
    def test_only_succeeded_runs_are_counted(self, db, status):
        _seed(db, tier="smart", durations=[600.0] * 30, status=status)
        summary = _recompute(db)

        assert summary["smart"]["sample_size"] == 0
        assert service.get_published_tier_durations(db, now=NOW) == {}

    def test_a_failed_run_does_not_dilute_a_publishable_tier(self, db):
        _seed(db, tier="smart", durations=[600.0] * service.MIN_SAMPLE_SIZE)
        # A failure that ran for an hour before giving up would drag any
        # statistic that counted it.
        _seed(db, tier="smart", durations=[3600.0] * 20, status="failed")
        _recompute(db)

        figure = service.get_published_tier_durations(db, now=NOW)["smart"]
        assert figure.sample_size == service.MIN_SAMPLE_SIZE
        assert figure.high_minutes == 10

    def test_sitemap_crawl_children_are_distinguishable_and_excluded(self, db):
        # audit_jobs.sitemap_crawl_job_id is the FK that makes them
        # distinguishable; a crawl queues one job per URL, and those runs
        # describe a crawl's internals, not the depth a customer chose.
        crawl = models.SitemapCrawlJob(
            id=str(uuid.uuid4()),
            user_id=db.info["user_id"],
            project_id=db.info["project_id"],
            status="succeeded",
            sitemap_url="https://example.com/sitemap.xml",
        )
        db.add(crawl)
        db.commit()

        _seed(db, tier="smart", durations=[600.0] * service.MIN_SAMPLE_SIZE)
        _seed(
            db,
            tier="smart",
            durations=[30.0] * 40,
            sitemap_crawl_job_id=crawl.id,
        )
        _recompute(db)

        figure = service.get_published_tier_durations(db, now=NOW)["smart"]
        assert figure.sample_size == service.MIN_SAMPLE_SIZE
        assert (figure.low_minutes, figure.high_minutes) == (10, 10)

    def test_signal_initiated_competitor_refreshes_are_excluded(self, db):
        _seed(db, tier="fast", durations=[300.0] * service.MIN_SAMPLE_SIZE)
        _seed(db, tier="fast", durations=[30.0] * 40, scan_origin="competitor_refresh")
        _recompute(db)

        figure = service.get_published_tier_durations(db, now=NOW)["fast"]
        assert figure.sample_size == service.MIN_SAMPLE_SIZE

    def test_an_undeclared_scan_origin_is_still_counted(self, db):
        # NULL scan_origin means the write path declared nothing, not that the
        # run was Signal's. Dropping those rows would silently shrink the
        # sample, so the query allows NULL explicitly.
        _seed(db, tier="fast", durations=[300.0] * service.MIN_SAMPLE_SIZE, scan_origin=None)
        _recompute(db)

        assert (
            service.get_published_tier_durations(db, now=NOW)["fast"].sample_size
            == service.MIN_SAMPLE_SIZE
        )

    def test_runs_outside_the_window_are_excluded(self, db):
        _seed(
            db,
            tier="smart",
            durations=[600.0] * 30,
            completed_days_ago=service.WINDOW_DAYS + 5,
        )
        summary = _recompute(db)

        assert summary["smart"]["sample_size"] == 0

    def test_rows_with_missing_timestamps_are_excluded(self, db):
        _seed(db, tier="smart", durations=[600.0] * 10, started_at=None)
        _seed(db, tier="smart", durations=[600.0] * 10, completed_at=None)
        summary = _recompute(db)

        assert summary["smart"]["sample_size"] == 0

    def test_non_positive_durations_are_excluded(self, db):
        # Clock skew, not a run.
        _seed(db, tier="smart", durations=[0.0] * 10 + [-120.0] * 10)
        summary = _recompute(db)

        assert summary["smart"]["sample_size"] == 0

    def test_lite_is_never_aggregated(self, db):
        _seed(db, tier="lite", durations=[30.0] * 40)
        _recompute(db)

        published = service.get_published_tier_durations(db, now=NOW)
        assert "lite" not in published
        assert db.query(models.AuditTierDurationStat).filter_by(tier="lite").count() == 0


# ── Recompute is idempotent and upserts ──────────────────────────────────────


class TestRecompute:
    def test_recompute_upserts_one_row_per_tier(self, db):
        _seed(db, tier="fast", durations=[300.0] * service.MIN_SAMPLE_SIZE)
        _recompute(db)
        _recompute(db)

        rows = db.query(models.AuditTierDurationStat).all()
        assert len(rows) == len(service.AGGREGATED_TIERS)
        assert {row.tier for row in rows} == set(service.AGGREGATED_TIERS)

    def test_a_tier_that_falls_below_the_threshold_stops_publishing(self, db):
        _seed(db, tier="fast", durations=[300.0] * service.MIN_SAMPLE_SIZE)
        _recompute(db)
        assert "fast" in service.get_published_tier_durations(db, now=NOW)

        # Every run ages out of the window; the figure must disappear rather
        # than linger as the last thing that was true.
        db.query(models.AuditJob).delete()
        db.commit()
        _recompute(db)

        assert service.get_published_tier_durations(db, now=NOW) == {}
        row = db.query(models.AuditTierDurationStat).filter_by(tier="fast").one()
        assert row.p50_seconds is None


# ── Rendering for the support surfaces ───────────────────────────────────────


class TestDescribePublishedTierDurations:
    LABELS = {"fast": "Fast", "smart": "Smart", "deep_judgment": "High Confidence"}

    def test_renders_only_the_tiers_with_a_measured_figure(self, db):
        _seed(db, tier="smart", durations=[600.0] * service.MIN_SAMPLE_SIZE)
        _seed(db, tier="fast", durations=[120.0] * 2)
        _recompute(db)
        published = service.get_published_tier_durations(db, now=NOW)

        rendered = service.describe_published_tier_durations(published, labels=self.LABELS)

        assert rendered == "- Smart: half of the last 20 scans finished within 10 minutes."
        assert "Fast" not in rendered
        assert "High Confidence" not in rendered

    def test_returns_none_when_nothing_is_publishable(self, db):
        _seed(db, tier="smart", durations=[600.0] * 3)
        _recompute(db)
        published = service.get_published_tier_durations(db, now=NOW)

        assert service.describe_published_tier_durations(published, labels=self.LABELS) is None
        assert (
            service.describe_published_tier_durations(published, labels=self.LABELS, inline=True)
            is None
        )

    def test_inline_rendering_is_one_sentence_fragment(self, db):
        _seed(db, tier="fast", durations=[60.0 * n for n in range(1, 21)])
        _recompute(db)
        published = service.get_published_tier_durations(db, now=NOW)

        rendered = service.describe_published_tier_durations(
            published, labels=self.LABELS, inline=True
        )

        assert rendered == "Fast: half of the last 20 scans finished in 5 to 16 minutes."
        assert "\n" not in rendered
