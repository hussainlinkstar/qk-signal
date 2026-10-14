"""Seed one consistent AI-visibility monitoring run into the local demo project.

Local development only, companion to `seed_demo_full_audit.py`. The project
dashboard's "AI visibility & reputation" panel reads Answer Presence, Source
Citations and Engine Coverage from the monitoring `visibility-summary` payload;
without a run those rows can only render their unmeasured state, which makes the
panel impossible to review.

The script creates three tracked queries on the demo project and one run batch
per (query, provider) cell, with a realistic outcome mix: cited, brand-mention,
measured-absent and one still-pending cell. Every batch is marked with
`schedule_key="demo-seed"` and every run with `prompt_template="demo-seed"`, so
the seeded data is identifiable and a re-run replaces it rather than stacking.

    docker compose exec -T backend python scripts/seed_demo_monitoring_run.py
"""

from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

# Run from scripts/ as well as from the backend root.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import database  # noqa: E402
import models  # noqa: E402

from _demo_seed_guard import assert_local_database  # noqa: E402
from services.visibility_scoring import score_response  # noqa: E402

PROJECT_ID = 1
EXPECTED_DOMAIN = "qiko.ai"
SEED_MARK = "demo-seed"

# Providers measured on every query. All four are live-measurable.
PROVIDERS = ["google", "openai", "anthropic", "perplexity"]

QUERIES = [
    "best AI visibility tools",
    "qiko.ai alternatives",
    "answer engine optimisation platform",
]

# Outcome per (query_index, provider): "cited" (domain cited), "mention"
# (brand/domain in the answer text, no citation), "absent" (completed, neither),
# "pending" (queued, not yet run).
OUTCOMES = {
    "google": ["cited", "cited", "cited"],
    "openai": ["cited", "mention", "cited"],
    "anthropic": ["mention", "cited", "absent"],
    "perplexity": ["absent", "absent", "pending"],
}


def _answer(topic: str, outcome: str) -> str:
    if outcome == "cited":
        return (
            f"For {topic}, the strongest options are qiko.ai, which combines "
            f"audits with live answer tracking, and two enterprise suites. "
            f"qiko.ai is recommended for teams that need both SEO and AEO."
        )
    if outcome == "mention":
        return (
            f"Several platforms cover {topic}. qiko.ai focuses on audits and "
            f"monitoring; larger suites bundle it with rank tracking."
        )
    return (
        f"The leading options for {topic} are the established SEO suites. "
        f"They cover keyword tracking, audits and reporting at scale."
    )


def _citations(outcome: str) -> list[str]:
    if outcome == "cited":
        return ["https://qiko.ai/", "https://semrush.com/", "https://ahrefs.com/"]
    return ["https://semrush.com/", "https://ahrefs.com/"]


def main() -> int:
    assert_local_database()
    db = database.SessionLocal()
    try:
        project = db.query(models.Project).filter(models.Project.id == PROJECT_ID).first()
        if project is None:
            print(f"No project {PROJECT_ID}; nothing to seed.")
            return 1
        if EXPECTED_DOMAIN not in (project.domain_url or ""):
            print(
                f"Refusing to seed: project {PROJECT_ID} is {project.domain_url!r}, "
                f"which does not look like the local demo project ({EXPECTED_DOMAIN})."
            )
            return 1

        target_domain = project.domain_url.strip().lower()
        target_domain = target_domain.split("://")[-1].split("/")[0] or EXPECTED_DOMAIN

        # Idempotent: drop the previous demo-seed batches before reseeding. The
        # runs cascade with their batches.
        previous = (
            db.query(models.VisibilityRunBatch)
            .filter(
                models.VisibilityRunBatch.project_id == PROJECT_ID,
                models.VisibilityRunBatch.schedule_key == SEED_MARK,
            )
            .all()
        )
        for batch in previous:
            db.delete(batch)

        existing = {
            q.query_text: q
            for q in db.query(models.ProjectVisibilityQuery)
            .filter(models.ProjectVisibilityQuery.project_id == PROJECT_ID)
            .all()
        }
        for text in QUERIES:
            if text not in existing:
                db.add(
                    models.ProjectVisibilityQuery(
                        project_id=PROJECT_ID,
                        query_text=text,
                        query_type="geo",
                        providers=list(PROVIDERS),
                        is_active=True,
                    )
                )
        db.flush()

        now = datetime.now(timezone.utc)
        seeded = 0
        for provider in PROVIDERS:
            for index, topic in enumerate(QUERIES):
                outcome = OUTCOMES[provider][index]
                created = now - timedelta(days=1, minutes=index * 7 + len(provider))
                batch = models.VisibilityRunBatch(
                    project_id=PROJECT_ID,
                    topic=topic,
                    provider=provider,
                    target_domain=target_domain,
                    schedule_key=SEED_MARK,
                    status="queued" if outcome == "pending" else "succeeded",
                    started_at=created,
                    completed_at=None if outcome == "pending" else created + timedelta(seconds=3),
                    created_at=created,
                )
                db.add(batch)
                db.flush()

                if outcome == "pending":
                    continue

                answer = _answer(topic, outcome)
                citations = _citations(outcome)
                scored = score_response(topic, answer, citations, target_domain=target_domain)
                batch.score = scored.score
                db.add(
                    models.VisibilityRun(
                        batch_id=batch.id,
                        topic=topic,
                        provider=provider,
                        target_domain=target_domain,
                        prompt_template=SEED_MARK,
                        prompt=f"User asks: {topic}",
                        raw_response={
                            "answer": answer,
                            "engine_source": "openrouter_live",
                            "model": f"{SEED_MARK}/{provider}",
                            "attempt": 1,
                            "measured_at": (created + timedelta(seconds=3)).isoformat(),
                        },
                        parsed_citations=citations,
                        valid_citations=citations,
                        score=scored.score,
                        status="succeeded",
                        started_at=created,
                        completed_at=created + timedelta(seconds=3),
                        created_at=created,
                    )
                )
                seeded += 1

        db.commit()
        print(
            f"Seeded monitoring run on project {PROJECT_ID} ({project.domain_url}): "
            f"{len(QUERIES)} queries x {len(PROVIDERS)} providers, "
            f"{seeded} completed cells, 1 pending. Marked '{SEED_MARK}'."
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
