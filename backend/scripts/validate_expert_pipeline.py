from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.env_bootstrap import bootstrap_environment

bootstrap_environment()

import models  # noqa: E402
from core.config import settings  # noqa: E402
from core.redis_client import get_sync_redis  # noqa: E402
from database import SessionLocal  # noqa: E402

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_PROJECT_ID = 2
DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
REPO_ROOT = Path(__file__).resolve().parents[2]
DB_ACCESS_MODE = "direct"

FRONTEND_PROJECT_PROFILE = {
    "project_name": "Lavan Events",
    "primary_domain": "https://lavan.ro",
    "target_country": "RO",
    "language": "ro",
    "reporting_language": "Romanian (RO)",
    "market_region": "Romania",
    "local_market": "Iasi, Romania",
    "category": "Local Business - Event Planner & Wedding Services",
    "service_categories": [
        "Wedding planner",
        "Wedding florist",
        "Wedding decorations",
    ],
    "icp_roles": [
        "Newlyweds",
        "Females",
        "Females 24-35",
    ],
    "pain_points": (
        "Cuplurile din Iasi cauta un furnizor premium care sa combine planificarea, "
        "decorul floral si executia fara coordonarea mai multor vendori separati. "
        "Clientii au nevoie de inspiratie vizuala, incredere, transparenta si dovada "
        "clara ca brandul poate livra evenimente elegante si coerente."
    ),
    "usp": (
        "Serviciu premium integrat pentru wedding planning, wedding florist si decor de "
        "eveniment, cu executie coerenta si directie vizuala unificata pentru nunti si "
        "evenimente private in Iasi."
    ),
    "priority_tags": [
        "GEO",
        "AEO",
        "SEO",
        "Wedding planner",
        "Wedding florist",
        "Event decor",
        "Iasi",
        "Romania",
        "Brand authority",
        "Local visibility",
    ],
    "expertise_authority_sources": [
        "Google Business Profile",
        "Instagram portfolio",
        "Facebook page",
        "Client event portfolio",
        "Wedding and event vendor partnerships",
        "Local venue collaborations",
    ],
}

TARGET_ENTITIES = [
    "Cupluri logodite",
    "Mirese premium",
    "Parinti pentru botez",
    "Clienti evenimente private",
    "Wedding planners",
    "Locatii de evenimente",
]

COMPETITOR_ENTITIES = [
    "Design floral premium Iasi",
    "Decor evenimente Iasi",
    "Wedding planners locali",
    "Ateliere florale",
    "Ballroom-uri cu decor inclus",
    "Agentii full-service evenimente",
]

ENTITY_CONFIGURATION = [*TARGET_ENTITIES, *COMPETITOR_ENTITIES]

BRAND_TRUTH_PAYLOAD = {
    "brand_name": FRONTEND_PROJECT_PROFILE["project_name"],
    "primary_domain": FRONTEND_PROJECT_PROFILE["primary_domain"],
    "website_url": FRONTEND_PROJECT_PROFILE["primary_domain"],
    "target_country": FRONTEND_PROJECT_PROFILE["target_country"],
    "language": FRONTEND_PROJECT_PROFILE["language"],
    "reporting_language": FRONTEND_PROJECT_PROFILE["reporting_language"],
    "market_region": FRONTEND_PROJECT_PROFILE["market_region"],
    "local_market": FRONTEND_PROJECT_PROFILE["local_market"],
    "category": FRONTEND_PROJECT_PROFILE["category"],
    "service_categories": list(FRONTEND_PROJECT_PROFILE["service_categories"]),
    "icp_roles": list(FRONTEND_PROJECT_PROFILE["icp_roles"]),
    "pain_points": FRONTEND_PROJECT_PROFILE["pain_points"],
    "usp": FRONTEND_PROJECT_PROFILE["usp"],
    "priority_tags": list(FRONTEND_PROJECT_PROFILE["priority_tags"]),
    "expertise_authority_sources": list(FRONTEND_PROJECT_PROFILE["expertise_authority_sources"]),
    "target_entities": list(TARGET_ENTITIES),
    "competitors": list(COMPETITOR_ENTITIES),
}


@dataclass(frozen=True)
class ValidationCase:
    key: str
    provider: str
    tier: str
    audit_target_type: str
    target_name: str
    url: str | None
    expect_specialist_synthesis: bool
    expect_track_b: bool


VALIDATION_CASES: tuple[ValidationCase, ...] = (
    ValidationCase(
        key="google-website-smart",
        provider="google",
        tier="smart",
        audit_target_type="website",
        target_name="Lavan Events",
        url="https://lavan.ro",
        expect_specialist_synthesis=False,
        expect_track_b=False,
    ),
    ValidationCase(
        key="google-brand-smart",
        provider="google",
        tier="smart",
        audit_target_type="brand",
        target_name="Lavan Events",
        url=None,
        expect_specialist_synthesis=False,
        expect_track_b=False,
    ),
    ValidationCase(
        key="anthropic-website-smart",
        provider="anthropic",
        tier="smart",
        audit_target_type="website",
        target_name="Lavan Events",
        url="https://lavan.ro",
        expect_specialist_synthesis=True,
        expect_track_b=False,
    ),
    ValidationCase(
        key="anthropic-brand-smart",
        provider="anthropic",
        tier="smart",
        audit_target_type="brand",
        target_name="Lavan Events",
        url=None,
        expect_specialist_synthesis=True,
        expect_track_b=False,
    ),
    ValidationCase(
        key="anthropic-website-deep",
        provider="anthropic",
        tier="deep_judgment",
        audit_target_type="website",
        target_name="Lavan Events",
        url="https://lavan.ro",
        expect_specialist_synthesis=True,
        expect_track_b=True,
    ),
    ValidationCase(
        key="anthropic-brand-deep",
        provider="anthropic",
        tier="deep_judgment",
        audit_target_type="brand",
        target_name="Lavan Events",
        url=None,
        expect_specialist_synthesis=True,
        expect_track_b=True,
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the TASK-62 audit matrix against existing request_ids or, "
            "with explicit confirmation, queue live audits."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--project-id", type=int, default=DEFAULT_PROJECT_ID)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--poll-interval-seconds", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS
    )
    parser.add_argument(
        "--case",
        action="append",
        choices=[case.key for case in VALIDATION_CASES],
        help="Restrict queue/validation to one or more matrix cases.",
    )
    parser.add_argument(
        "--request-id",
        action="append",
        default=[],
        metavar="CASE=REQUEST_ID",
        help="Validate an existing persisted run without queueing a live audit.",
    )
    parser.add_argument(
        "--queue-live",
        action="store_true",
        help="Explicitly queue live audits for the selected cases.",
    )
    parser.add_argument(
        "--purge-queue-first",
        action="store_true",
        help="Purge Redis audit queue before queueing live audits.",
    )
    args = parser.parse_args()
    if not args.queue_live and not args.request_id:
        parser.error(
            "Nothing to do. Pass --request-id CASE=REQUEST_ID to validate existing audits, "
            "or --queue-live to queue live audits."
        )
    if args.purge_queue_first and not args.queue_live:
        parser.error("--purge-queue-first requires --queue-live.")
    return args


def purge_audit_queue() -> None:
    try:
        with get_sync_redis() as redis_client:
            pending = int(redis_client.llen(settings.AUDIT_QUEUE_NAME) or 0)
            if pending > 0:
                redis_client.delete(settings.AUDIT_QUEUE_NAME)
            print(
                f"QUEUE purge: removed {pending} pending item(s) from {settings.AUDIT_QUEUE_NAME}"
            )
            return
    except Exception as exc:
        print(
            f"QUEUE purge: direct Redis connection failed ({exc}); falling back to docker compose"
        )

    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "redis",
            "redis-cli",
            "DEL",
            settings.AUDIT_QUEUE_NAME,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "failed to purge Redis queue via docker compose: "
            f"{result.stderr.strip() or result.stdout.strip() or result.returncode}"
        )
    print(
        "QUEUE purge: docker compose fallback completed for "
        f"{settings.AUDIT_QUEUE_NAME} result={result.stdout.strip() or 'ok'}"
    )


def _run_backend_python(code: str, *args: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "backend", "python", "-c", code, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "docker compose backend fallback failed: "
            f"{result.stderr.strip() or result.stdout.strip() or result.returncode}"
        )
    return result.stdout.strip()


def _fetch_jobs_via_docker(request_ids: list[str]) -> list[dict[str, Any]]:
    payload = _run_backend_python(
        """
import json, sys
sys.path.insert(0, '/app')
from core.env_bootstrap import bootstrap_environment
bootstrap_environment()
from database import SessionLocal
import models

request_ids = json.loads(sys.argv[1])
with SessionLocal() as db:
    rows = (
        db.query(models.AuditJob)
        .filter(models.AuditJob.request_id.in_(request_ids))
        .all()
    )
    print(json.dumps([
        {
            "id": row.id,
            "request_id": row.request_id,
            "status": row.status,
            "provider": row.provider,
            "tier": row.tier,
            "audit_target_type": str(row.audit_target_type),
            "error": row.error,
        }
        for row in rows
    ]))
""",
        json.dumps(request_ids),
    )
    return json.loads(payload) if payload else []


def _fetch_audits_via_docker(request_ids: list[str]) -> dict[str, dict[str, Any]]:
    payload = _run_backend_python(
        """
import json, sys
sys.path.insert(0, '/app')
from core.env_bootstrap import bootstrap_environment
bootstrap_environment()
from database import SessionLocal
import models

request_ids = json.loads(sys.argv[1])
with SessionLocal() as db:
    rows = (
        db.query(models.Audit)
        .filter(models.Audit.request_id.in_(request_ids))
        .all()
    )
    print(json.dumps({
        str(row.request_id): {
            "id": row.id,
            "target_url": row.target_url,
            "audit_target_type": str(row.audit_target_type),
            "full_report": row.full_report,
        }
        for row in rows
        if isinstance(row.full_report, dict)
    }))
""",
        json.dumps(request_ids),
    )
    return json.loads(payload) if payload else {}


def _fetch_jobs(request_ids: list[str]) -> list[dict[str, Any]]:
    global DB_ACCESS_MODE

    if DB_ACCESS_MODE == "docker_compose":
        return _fetch_jobs_via_docker(request_ids)

    try:
        with SessionLocal() as db:
            rows = (
                db.query(models.AuditJob).filter(models.AuditJob.request_id.in_(request_ids)).all()
            )
            return [
                {
                    "id": row.id,
                    "request_id": row.request_id,
                    "status": row.status,
                    "provider": row.provider,
                    "tier": row.tier,
                    "audit_target_type": str(row.audit_target_type),
                    "error": row.error,
                }
                for row in rows
            ]
    except Exception as exc:
        DB_ACCESS_MODE = "docker_compose"
        print(f"DB access: direct connection failed ({exc}); falling back to docker compose")
        return _fetch_jobs_via_docker(request_ids)


def _fetch_audits(request_ids: list[str]) -> dict[str, dict[str, Any]]:
    global DB_ACCESS_MODE

    if DB_ACCESS_MODE == "docker_compose":
        return _fetch_audits_via_docker(request_ids)

    try:
        with SessionLocal() as db:
            rows = db.query(models.Audit).filter(models.Audit.request_id.in_(request_ids)).all()
            return {
                str(row.request_id): {
                    "id": row.id,
                    "target_url": row.target_url,
                    "audit_target_type": str(row.audit_target_type),
                    "full_report": row.full_report,
                }
                for row in rows
                if isinstance(row.full_report, dict)
            }
    except Exception as exc:
        DB_ACCESS_MODE = "docker_compose"
        print(f"DB access: direct connection failed ({exc}); falling back to docker compose")
        return _fetch_audits_via_docker(request_ids)


def build_payload(case: ValidationCase, *, project_id: int, request_id: str) -> dict[str, Any]:
    target_metadata = {
        "project_name": FRONTEND_PROJECT_PROFILE["project_name"],
        "primary_domain": FRONTEND_PROJECT_PROFILE["primary_domain"],
        "target_country": FRONTEND_PROJECT_PROFILE["target_country"],
        "language": FRONTEND_PROJECT_PROFILE["language"],
        "reporting_language": FRONTEND_PROJECT_PROFILE["reporting_language"],
        "market_region": FRONTEND_PROJECT_PROFILE["market_region"],
        "local_market": FRONTEND_PROJECT_PROFILE["local_market"],
        "category": FRONTEND_PROJECT_PROFILE["category"],
        "service_categories": list(FRONTEND_PROJECT_PROFILE["service_categories"]),
        "icp_roles": list(FRONTEND_PROJECT_PROFILE["icp_roles"]),
        "pain_points": FRONTEND_PROJECT_PROFILE["pain_points"],
        "usp": FRONTEND_PROJECT_PROFILE["usp"],
        "priority_tags": list(FRONTEND_PROJECT_PROFILE["priority_tags"]),
        "expertise_authority_sources": list(
            FRONTEND_PROJECT_PROFILE["expertise_authority_sources"]
        ),
        "target_entities": list(TARGET_ENTITIES),
        "competitors": list(COMPETITOR_ENTITIES),
        "validation_case": case.key,
    }
    audit_data = {
        "title": FRONTEND_PROJECT_PROFILE["project_name"],
        "summary": FRONTEND_PROJECT_PROFILE["usp"],
        "language": FRONTEND_PROJECT_PROFILE["language"],
        "market": FRONTEND_PROJECT_PROFILE["market_region"],
        "market_region": FRONTEND_PROJECT_PROFILE["market_region"],
        "category": FRONTEND_PROJECT_PROFILE["category"],
        "entities_detected": list(ENTITY_CONFIGURATION),
    }
    if case.url:
        audit_data["target_url"] = case.url
        audit_data["url"] = case.url
    return {
        "project_id": project_id,
        "provider": case.provider,
        "audit_target_type": case.audit_target_type,
        "url": case.url,
        "target_name": case.target_name,
        "tier": case.tier,
        "request_id": request_id,
        "language": FRONTEND_PROJECT_PROFILE["language"],
        "market": FRONTEND_PROJECT_PROFILE["market_region"],
        "category": FRONTEND_PROJECT_PROFILE["category"],
        "entities": ENTITY_CONFIGURATION,
        "brand_truth_payload": BRAND_TRUTH_PAYLOAD,
        "target_metadata": target_metadata,
        "audit_data": audit_data,
    }


def _cases_by_key() -> dict[str, ValidationCase]:
    return {case.key: case for case in VALIDATION_CASES}


def _select_cases(case_keys: list[str] | None) -> list[ValidationCase]:
    if not case_keys:
        return list(VALIDATION_CASES)
    cases_by_key = _cases_by_key()
    return [cases_by_key[key] for key in case_keys]


def _parse_existing_request_ids(raw_pairs: list[str]) -> dict[str, str]:
    cases_by_key = _cases_by_key()
    parsed: dict[str, str] = {}
    for raw_pair in raw_pairs:
        case_key, separator, request_id = raw_pair.partition("=")
        case_key = case_key.strip()
        request_id = request_id.strip()
        if separator != "=" or not case_key or not request_id:
            raise RuntimeError(f"invalid --request-id value {raw_pair!r}; expected CASE=REQUEST_ID")
        if case_key not in cases_by_key:
            raise RuntimeError(f"unknown validation case {case_key!r}")
        parsed[case_key] = request_id
    return parsed


def queue_cases(args: argparse.Namespace, selected_cases: list[ValidationCase]) -> dict[str, str]:
    request_ids: dict[str, str] = {}
    endpoint = f"{args.base_url.rstrip('/')}/api/v1/audit/jobs"
    timestamp = int(time.time())

    with requests.Session() as session:
        for case in selected_cases:
            request_id = f"task62-{case.key}-{timestamp}-{uuid4().hex[:8]}"
            response = session.post(
                endpoint,
                json=build_payload(case, project_id=args.project_id, request_id=request_id),
                timeout=90,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"queue failed for {case.key}: status={response.status_code} body={response.text}"
                )
            request_ids[case.key] = request_id
            print(f"QUEUED {case.key} request_id={request_id}")
    return request_ids


def poll_jobs(
    request_ids: dict[str, str], *, timeout_seconds: int, poll_interval_seconds: float
) -> None:
    deadline = time.time() + timeout_seconds
    remaining = set(request_ids.values())

    while remaining and time.time() < deadline:
        jobs = _fetch_jobs(list(remaining))
        terminal_request_ids = {
            str(job.get("request_id") or "")
            for job in jobs
            if str(job.get("status") or "").strip().lower() in {"succeeded", "failed"}
        }
        if terminal_request_ids:
            remaining -= terminal_request_ids
            for job in jobs:
                if str(job.get("request_id") or "") in terminal_request_ids:
                    print(
                        "JOB "
                        f"{job.get('request_id')} status={job.get('status')} "
                        f"target={job.get('audit_target_type')} tier={job.get('tier')}"
                    )
        if remaining:
            time.sleep(poll_interval_seconds)

    if remaining:
        raise RuntimeError("validation timed out waiting for jobs: " + ", ".join(sorted(remaining)))


def _assert_score_range(path: str, value: Any, failures: list[str]) -> None:
    if value is None:
        return
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        failures.append(f"{path}: expected numeric score, got {value!r}")
        return
    if numeric < 0 or numeric > 100:
        failures.append(f"{path}: expected 0-100, got {numeric}")


def _validate_signal_ranges(metadata: dict[str, Any], failures: list[str]) -> None:
    entity_analysis = (
        metadata.get("entity_analysis") if isinstance(metadata.get("entity_analysis"), dict) else {}
    )
    aeo_signals = (
        metadata.get("aeo_signals") if isinstance(metadata.get("aeo_signals"), dict) else {}
    )
    geo_signals = (
        metadata.get("geo_signals") if isinstance(metadata.get("geo_signals"), dict) else {}
    )
    technical_signals = (
        metadata.get("technical_signals")
        if isinstance(metadata.get("technical_signals"), dict)
        else {}
    )
    technical_performance = (
        technical_signals.get("performance")
        if isinstance(technical_signals.get("performance"), dict)
        else {}
    )

    for key, value in entity_analysis.items():
        if key.endswith("_score"):
            _assert_score_range(f"entity_analysis.{key}", value, failures)
    for key, value in aeo_signals.items():
        if key.endswith("_score") or key in {"schema_completeness", "featured_snippet_likelihood"}:
            _assert_score_range(f"aeo_signals.{key}", value, failures)
    for key, value in geo_signals.items():
        if key.endswith("_score"):
            _assert_score_range(f"geo_signals.{key}", value, failures)
    performance_score = technical_performance.get("score")
    if performance_score is not None:
        _assert_score_range("technical_signals.performance.score", performance_score, failures)


def _validate_case(
    case: ValidationCase,
    report_payload: dict[str, Any],
    audit_payload: dict[str, Any],
    failures: list[str],
) -> None:
    metadata = (
        report_payload.get("metadata") if isinstance(report_payload.get("metadata"), dict) else {}
    )
    ai_generation = (
        metadata.get("ai_generation") if isinstance(metadata.get("ai_generation"), dict) else {}
    )
    transcript = (
        ai_generation.get("transcript") if isinstance(ai_generation.get("transcript"), list) else []
    )
    transcript_roles = [
        str(item.get("role") or "").strip() for item in transcript if isinstance(item, dict)
    ]
    recommendations = (
        report_payload.get("recommendations")
        if isinstance(report_payload.get("recommendations"), dict)
        else {}
    )
    recommendation_items = (
        recommendations.get("items") if isinstance(recommendations.get("items"), list) else []
    )
    report_entities = (
        report_payload.get("entities") if isinstance(report_payload.get("entities"), list) else []
    )
    top_level_target = (
        report_payload.get("target") if isinstance(report_payload.get("target"), dict) else {}
    )

    if not recommendation_items:
        failures.append(f"{case.key}: recommendations is empty")
    for key in ("narrative", "seo", "geo", "aeo", "scores", "metadata", "target"):
        if not isinstance(report_payload.get(key), dict):
            failures.append(f"{case.key}: report is missing top-level dict section {key!r}")
    if not report_entities:
        failures.append(f"{case.key}: entities list is empty")

    _validate_signal_ranges(metadata, failures)

    if case.audit_target_type == "brand":
        if audit_payload.get("target_url"):
            failures.append(f"{case.key}: brand audit should not persist target_url")
        if top_level_target.get("url"):
            failures.append(f"{case.key}: brand report target.url should be empty")

    if case.provider == "google":
        if str(ai_generation.get("mode") or "").strip() != "single":
            failures.append(
                f"{case.key}: google path should remain single, got {ai_generation.get('mode')!r}"
            )
    else:
        if str(ai_generation.get("mode") or "").strip() != "specialist_synthesis":
            failures.append(
                f"{case.key}: anthropic path should be specialist_synthesis, got {ai_generation.get('mode')!r}"
            )
        if case.expect_track_b:
            if len(transcript) < 5:
                failures.append(
                    f"{case.key}: expected >=5 transcript entries, got {len(transcript)}"
                )
            if "track_b_judge" not in transcript_roles:
                failures.append(f"{case.key}: missing track_b_judge transcript entry")
            if metadata.get("dual_track_grounding_enabled") is not True:
                failures.append(f"{case.key}: deep_judgment run should enable dual-track grounding")
        else:
            if len(transcript) != 4:
                failures.append(f"{case.key}: expected 4 transcript entries, got {len(transcript)}")
            if "track_b_judge" in transcript_roles:
                failures.append(f"{case.key}: smart anthropic run should not include track_b_judge")


def validate_results(selected_cases: list[ValidationCase], request_ids: dict[str, str]) -> None:
    failures: list[str] = []
    jobs_by_request_id = {
        str(job.get("request_id") or ""): job for job in _fetch_jobs(list(request_ids.values()))
    }
    audits_by_request_id = _fetch_audits(list(request_ids.values()))

    for case in selected_cases:
        request_id = request_ids[case.key]
        job = jobs_by_request_id.get(request_id)
        if job is None:
            failures.append(f"{case.key}: missing audit_job for request_id={request_id}")
            continue
        if str(job.get("status") or "").strip().lower() != "succeeded":
            failures.append(
                f"{case.key}: job status={job.get('status')!r} "
                f"error={str(job.get('error') or '').strip() or 'n/a'}"
            )
            continue

        audit = audits_by_request_id.get(request_id)
        if not isinstance(audit, dict) or not isinstance(audit.get("full_report"), dict):
            failures.append(f"{case.key}: missing persisted audit report")
            continue

        try:
            _validate_case(case, audit["full_report"], audit, failures)
        except Exception as exc:
            failures.append(f"{case.key}: validation error: {exc}")
            continue

        print(
            "PASS "
            f"{case.key} audit_id={audit.get('id')} job_id={job.get('id')} "
            f"provider={job.get('provider')} tier={job.get('tier')}"
        )

    if failures:
        raise RuntimeError("validation failed:\n- " + "\n- ".join(failures))


def main() -> int:
    args = parse_args()
    selected_cases = _select_cases(args.case)
    request_ids = _parse_existing_request_ids(args.request_id)

    if request_ids:
        requested_case_keys = set(request_ids)
        selected_cases = [case for case in selected_cases if case.key in requested_case_keys]
        missing_case_keys = requested_case_keys - {case.key for case in selected_cases}
        if missing_case_keys:
            raise RuntimeError(
                "requested validation cases were filtered out unexpectedly: "
                + ", ".join(sorted(missing_case_keys))
            )

    if args.queue_live:
        if args.purge_queue_first:
            purge_audit_queue()
        queued_request_ids = queue_cases(args, selected_cases)
        request_ids.update(queued_request_ids)
        poll_jobs(
            request_ids,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )

    if request_ids:
        validate_results(selected_cases, request_ids)

    if request_ids:
        print(
            "VALIDATION summary: all selected TASK-62 cases passed "
            f"({len(selected_cases)} case(s))"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - manual validation helper
    raise SystemExit(main())
