#!/usr/bin/env python3
"""Why visibility runs did not reach the engine their provider slot names.

SIGV2-1300 acceptance item 2 asks for a breakdown per cause over the last seven
days. That answer was previously hand-written SQL, which is how two people get
two different numbers from the same database. This is the one command.

Read-only. Takes no arguments that mutate anything.

    python3 scripts/report_live_fallback_reasons.py            # last 7 days
    python3 scripts/report_live_fallback_reasons.py --days 1
    python3 scripts/report_live_fallback_reasons.py --project 22

Two scopes are reported separately and must not be added together. Runs with no
project are the global topic sweep: they have no workspace owner, so
``resolve_project_billing_context`` returns the fail-safe default and they are
served by the proxy by design. Counting them in a customer-facing live-versus-
proxy ratio is what produced the "99% proxy" figure that overstated the problem.

Runs recorded before SIGV2-1300 shipped carry no reason and appear as
``(not recorded)``. That is not a cause; it is the absence of one, and it
shrinks out of the window as the days pass.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import create_engine, text  # noqa: E402

REASON_ORDER = [
    "live_call_failed",
    "plan_not_entitled",
    "live_measurement_disabled",
    "engine_not_live_measurable",
]

QUERY = text(
    """
    SELECT
      CASE WHEN b.project_id IS NULL THEN 'seeding' ELSE 'project' END AS scope,
      r.provider,
      COALESCE(r.raw_response->>'engine_source', '(none)')   AS engine_source,
      COALESCE(r.raw_response->>'fallback_reason', '(not recorded)') AS reason,
      r.status,
      COUNT(*) AS runs
    FROM visibility_runs r
    JOIN visibility_run_batches b ON b.id = r.batch_id
    WHERE r.started_at >= NOW() - CAST(:window AS INTERVAL)
      AND (:project_id IS NULL OR b.project_id = :project_id)
    GROUP BY 1, 2, 3, 4, 5
    """
)


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        sys.exit("DATABASE_URL is not set. Run this where the backend's env is loaded.")
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", type=int, default=7, help="Window in days. Default 7."
    )
    parser.add_argument(
        "--project", type=int, default=None, help="Restrict to one project id."
    )
    args = parser.parse_args()

    engine = create_engine(_database_url())
    with engine.connect() as conn:
        rows = conn.execute(
            QUERY, {"window": f"{max(1, args.days)} days", "project_id": args.project}
        ).all()

    if not rows:
        print("No runs in the window.")
        return 0

    for scope in ("project", "seeding"):
        scoped = [r for r in rows if r.scope == scope]
        if not scoped:
            continue
        total = sum(r.runs for r in scoped)
        live = sum(r.runs for r in scoped if r.engine_source == "openrouter_live")
        label = (
            "PROJECT-SCOPED" if scope == "project" else "GLOBAL SEEDING (no project)"
        )
        print(f"\n{label}: {total} runs, {live} live ({live * 100 // max(1, total)}%)")

        by_reason: dict[str, int] = {}
        for row in scoped:
            if row.engine_source == "openrouter_live":
                continue
            by_reason[row.reason] = by_reason.get(row.reason, 0) + row.runs
        if not by_reason:
            print("  every run reached its named engine")
            continue

        print(f"  {'reason':<28} {'runs':>7}")
        ordered = sorted(
            by_reason.items(),
            key=lambda kv: (
                REASON_ORDER.index(kv[0])
                if kv[0] in REASON_ORDER
                else len(REASON_ORDER),
                -kv[1],
            ),
        )
        for reason, count in ordered:
            print(f"  {reason:<28} {count:>7}")

        failed = sum(r.runs for r in scoped if r.status == "failed")
        if failed:
            print(f"  of which failed outright: {failed}")

    print(
        "\nThe two scopes are different populations. Do not add them, and do not "
        "quote the seeding figure as a customer-facing number."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
