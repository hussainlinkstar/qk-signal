"""SIGV2-1229: no customer-facing sentence may name a cadence the sweep does not run.

The competitor gate was the live defect (it said "updated daily" while the
competitor sweep had been weekly since SIGV2-1208, fixed in
``frontend/src/i18n`` and pinned by ``refreshCadenceCopy.test.ts``). This file
covers the other half of the sweep: the plan catalogue, which is served on the
unauthenticated public surface and describes Standard as "Daily AI visibility
monitoring for a single brand."

That sentence is true today, because Standard's own-domain sweep is daily, and
it is one cadence change away from being false. The own-domain cadence is now
per plan (SIGV2-1188), so a plan description that names a frequency is a claim
about that plan's interval and has to be checked against it rather than read.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISABLE_TRACING", "1")

from app.config.plans import PLAN_PRESENTATION
from services.project_visibility_service import (
    VISIBILITY_SWEEP_DAILY_SECONDS,
    VISIBILITY_SWEEP_WEEKLY_SECONDS,
    plan_sweep_interval_seconds,
)

# The frequency words a plan description may use, and the interval each one
# asserts. A cadence with no word in this map (a 48-hour sweep, for instance)
# cannot be described in one word at all and has to be stated in days.
CADENCE_SECONDS_BY_WORD = {
    "hourly": 3600,
    "daily": VISIBILITY_SWEEP_DAILY_SECONDS,
    "weekly": VISIBILITY_SWEEP_WEEKLY_SECONDS,
    "monthly": 30 * VISIBILITY_SWEEP_DAILY_SECONDS,
}

_WORDS = re.compile(r"\b(hourly|daily|weekly|monthly)\b", re.IGNORECASE)


def _cadence_words(text: str) -> set[str]:
    return {match.lower() for match in _WORDS.findall(text or "")}


def test_a_plan_description_naming_a_cadence_names_its_own_cadence() -> None:
    for plan, presentation in PLAN_PRESENTATION.items():
        interval = plan_sweep_interval_seconds(plan)
        for field in ("description", "highlight"):
            for word in _cadence_words(str(presentation.get(field, ""))):
                assert word in CADENCE_SECONDS_BY_WORD, (plan, field, word)
                assert CADENCE_SECONDS_BY_WORD[word] == interval, (
                    f"{plan}.{field} says {word!r}, but its scheduled sweep runs "
                    f"every {interval}s"
                )


def test_the_standard_description_is_the_sentence_this_guards() -> None:
    """Named explicitly so a rewrite cannot quietly drop the claim being checked."""
    description = PLAN_PRESENTATION["plan_standard"]["description"]
    assert _cadence_words(description) == {"daily"}
    assert plan_sweep_interval_seconds("plan_standard") == VISIBILITY_SWEEP_DAILY_SECONDS


def test_starter_never_calls_its_weekly_sweep_daily() -> None:
    """Starter is the plan whose own-domain sweep is already weekly (SIGV2-1188)."""
    assert plan_sweep_interval_seconds("plan_starter") == VISIBILITY_SWEEP_WEEKLY_SECONDS
    presentation = PLAN_PRESENTATION["plan_starter"]
    joined = f"{presentation.get('description', '')} {presentation.get('highlight', '')}"
    assert "daily" not in joined.lower()
