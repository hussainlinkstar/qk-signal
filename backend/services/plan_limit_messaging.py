"""Shared refusal wording for per-plan caps on tracked resources.

A cap refusal has to name the cap, what is already in use, what remains and the
plan that lifts it; a refusal the customer cannot act on is the defect
SIGV2-1142 fixed for tracked prompts. Tracked keywords are the same class of
resource (metered per monitoring cycle, capped per plan, SIGV2-1150), so both
build the sentence here instead of each service inventing its own.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.config.plans import PLAN_PRESENTATION, PLAN_WEIGHTS, PRIVATE_PLAN_IDS


def plan_display_name(plan: str) -> str:
    """Customer-facing name for a canonical plan id."""
    presentation = PLAN_PRESENTATION.get(plan)
    if presentation and presentation.get("name"):
        return str(presentation["name"])
    return plan.replace("plan_", "").replace("_", " ").title()


def _rank(allowance: int) -> float:
    """A negative allowance means unlimited, so it ranks above every finite cap."""
    return float("inf") if allowance < 0 else float(allowance)


def next_plan_with_higher_allowance(
    plan: str,
    allowances: Mapping[str, int],
) -> tuple[str, int] | None:
    """The cheapest purchasable plan above ``plan`` that allows more of it.

    ``allowances`` maps a canonical plan id to that plan's cap for one tracked
    resource. Returns ``None`` when nothing higher raises it.

    Plans in ``PRIVATE_PLAN_IDS`` are never named. The agency trial sits above
    Starter by weight and tracks more of both resources, so it used to be the
    answer for a Starter customer, but it is a free 14-day evaluation grant
    rather than something anyone can buy: naming it told a customer to upgrade
    to a plan that does not exist as a purchase (SIGV2-1150).
    """
    current_rank = _rank(int(allowances.get(plan, 0)))
    current_weight = PLAN_WEIGHTS.get(plan, 0)

    candidates = [
        (PLAN_WEIGHTS.get(candidate, 0), candidate, int(allowance))
        for candidate, allowance in allowances.items()
        if candidate not in PRIVATE_PLAN_IDS
        and PLAN_WEIGHTS.get(candidate, 0) > current_weight
        and _rank(int(allowance)) > current_rank
    ]
    if not candidates:
        return None

    _, best_plan, best_allowance = min(candidates)
    return best_plan, best_allowance


def tracked_limit_detail(
    *,
    plan: str | None,
    used: int,
    maximum: int,
    allowances: Mapping[str, int],
    noun_singular: str,
    noun_plural: str,
) -> str:
    """Say what the cap is, what is used, what remains, and what lifts it."""
    remaining = max(0, maximum - used)
    plan_part = f"your {plan_display_name(plan)} plan tracks" if plan else "this plan tracks"
    detail = (
        f"{noun_singular.capitalize()} limit reached: {plan_part} {maximum} {noun_plural}, "
        f"{used} are in use and {remaining} remain."
    )

    upgrade = next_plan_with_higher_allowance(plan, allowances) if plan else None
    if upgrade:
        upgrade_plan, upgrade_allowance = upgrade
        allowance_part = (
            f"unlimited {noun_plural}" if upgrade_allowance < 0 else str(upgrade_allowance)
        )
        detail += (
            f" Remove a {noun_singular}, or upgrade to {plan_display_name(upgrade_plan)} "
            f"to track {allowance_part}."
        )
    else:
        detail += f" Remove a {noun_singular} you no longer track to add this one."
    return detail
