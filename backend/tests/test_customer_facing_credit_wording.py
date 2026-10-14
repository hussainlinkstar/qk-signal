"""SIGV2-1143: no backend-authored customer string is denominated in credits.

The frontend half of this rule is pinned by
``frontend/src/components/billing/creditWording.test.tsx``, which scans
frontend files. That guard could not see these leaks, because the strings are
authored in the backend and reach the customer as data: the plan catalogue
description rendered on the plans list, the capability label a plan diff can
pick up, and the support assistant prompt, which the model repeats in
conversation no matter how clean the interface is.

Scope, stated plainly so a later reader does not mistake this for a full audit
of the boundary. It covers strings authored in ``app/config/plans.py`` and
``services/support_chat_service.py``. Two *numeric* exposures of
``credits_per_month`` survive outside those two files and are reported on the
ticket instead of being quietly pinned here:
``services/public_plan_catalog.py`` publishes ``credits_per_month`` in the
unauthenticated pricing payload, and ``billing/router.py`` returns the whole
capabilities matrix on the authenticated plan list.

The prompt keeps literal plan figures rather than interpolating the matrix, so
the figures are pinned to the matrix here instead: drift fails a test rather
than reaching a customer as a confident wrong number. The same holds for the
plan table in the injected knowledge pack.

The injected surface is covered as a whole, not just the prompt template.
``knowledge_service`` loads every ``.md`` file under
``app/domain_knowledge/`` when no category is requested, and
``build_support_chat_prompt`` hands that text to the model as a declared source
of truth, so each of those files is customer-facing copy. One assertion builds
the prompt with the real domain context, and the directory is swept file by
file, so a new file in there is covered the moment it is added.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config.plans import (  # noqa: E402
    CANONICAL_PLAN_TYPES,
    CAPABILITY_DESCRIPTIONS,
    CAPABILITY_MATRIX,
    INTERNAL_CAPABILITY_KEYS,
    PLAN_PRESENTATION,
    PRIVATE_PLAN_IDS,
    PUBLIC_PLAN_TYPES,
    TRIAL_DURATION_DAYS,
    TRIAL_MAX_AUDITS,
    TRIAL_SCAN_ALLOWANCE,
    build_plan_feature_list,
    customer_facing_capability_label,
    customer_facing_monthly_price_usd,
    diff_capabilities,
    get_plan_catalog_entry,
    is_custom_priced,
)
from services.support_chat_service import build_support_chat_prompt  # noqa: E402

CREDIT = re.compile(r"credit", re.IGNORECASE)
TOP_UP = re.compile(r"top[\s-]?up", re.IGNORECASE)
FORMER_BRAND = re.compile(r"thothgraph", re.IGNORECASE)

TRIAL_PLAN = "plan_agency_trial"
METERED_PLANS = ("plan_standard", "plan_specialist", "plan_executive")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = BACKEND_ROOT / "app" / "domain_knowledge"
PRODUCT_KNOWLEDGE = KNOWLEDGE_DIR / "qiko_signal_product.md"
KNOWLEDGE_FILES = sorted(KNOWLEDGE_DIR.glob("*.md"))


def _support_prompt() -> str:
    return build_support_chat_prompt(
        [{"role": "user", "content": "How many scans does my plan include?"}],
        "en",
    )


# --- the plan catalogue -----------------------------------------------------


@pytest.mark.parametrize("plan", CANONICAL_PLAN_TYPES)
def test_plan_presentation_is_credit_free(plan: str) -> None:
    presentation = PLAN_PRESENTATION[plan]
    leaks = [value for value in presentation.values() if CREDIT.search(value)]
    assert leaks == [], f"{plan} presentation is denominated in credits: {leaks}"


@pytest.mark.parametrize("plan", CANONICAL_PLAN_TYPES)
def test_plan_catalog_entry_strings_are_credit_free(plan: str) -> None:
    """The served catalogue entry, which is what the plans list renders."""
    entry = get_plan_catalog_entry(plan)
    strings = [value for value in entry.values() if isinstance(value, str)]
    strings += [str(feature) for feature in build_plan_feature_list(plan)]
    leaks = [value for value in strings if CREDIT.search(value)]
    assert leaks == [], f"{plan} catalogue copy is denominated in credits: {leaks}"


def test_capability_labels_are_credit_free() -> None:
    leaks = {key: value for key, value in CAPABILITY_DESCRIPTIONS.items() if CREDIT.search(value)}
    assert leaks == {}, f"capability labels are denominated in credits: {leaks}"


def test_every_capability_key_still_has_a_label() -> None:
    """Rewording a label must not drop the admin plans screen's coverage."""
    for plan, capabilities in CAPABILITY_MATRIX.items():
        missing = sorted(set(capabilities) - set(CAPABILITY_DESCRIPTIONS))
        assert missing == [], f"{plan} has undescribed capabilities: {missing}"


def test_internal_capability_keys_have_no_customer_label() -> None:
    assert "credits_per_month" in INTERNAL_CAPABILITY_KEYS
    for key in INTERNAL_CAPABILITY_KEYS:
        assert customer_facing_capability_label(key) is None
        # The key itself stays in the matrix: trial_service,
        # plan_credit_grant_service and billing/usage_analytics read it.
        assert key in CAPABILITY_MATRIX["plan_standard"]


@pytest.mark.parametrize("current", CANONICAL_PLAN_TYPES)
@pytest.mark.parametrize("target", CANONICAL_PLAN_TYPES)
def test_plan_diffs_never_label_an_internal_unit(current: str, target: str) -> None:
    """Covers the skip list and the titled-key fallback behind it.

    Dropping ``credits_per_month`` from ``_SKIP_KEYS`` used to produce a
    "Credits Per Month" label from the fallback. It cannot now, because an
    internal key has no customer label at all.
    """
    diff = diff_capabilities(current, target)
    leaks = [label for label in diff["gained"] + diff["lost"] if CREDIT.search(label)]
    assert leaks == [], f"{current} -> {target} diff leaked: {leaks}"


# --- what the trial actually grants ----------------------------------------


def test_trial_description_states_the_scan_allowance_from_max_audits() -> None:
    description = PLAN_PRESENTATION[TRIAL_PLAN]["description"]
    assert TRIAL_SCAN_ALLOWANCE == int(CAPABILITY_MATRIX[TRIAL_PLAN]["max_audits"])
    assert description == (
        f"{TRIAL_DURATION_DAYS}-day free trial with {TRIAL_SCAN_ALLOWANCE} full scans."
    )
    assert not CREDIT.search(description)
    assert "audit" not in description.lower()


def test_trial_grant_is_the_max_audits_ceiling_not_a_credit_figure() -> None:
    """The allowance a trialling customer hits is ``max_audits``, exactly.

    An exhausted internal balance does not refuse a scan (SIGV2-1024), so the
    credit grant is not what the customer experiences and cannot be converted
    into scans at any rate.
    """
    from services.trial_service import enforce_trial_audit_limit

    assert TRIAL_MAX_AUDITS == TRIAL_SCAN_ALLOWANCE

    def _trial_user(audits_used: int) -> SimpleNamespace:
        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            trial_plan=TRIAL_PLAN,
            trial_started_at=now,
            trial_ends_at=now + timedelta(days=TRIAL_DURATION_DAYS),
            trial_audits_used=audits_used,
            trial_max_audits=TRIAL_SCAN_ALLOWANCE,
            trial_initial_credits=0,
            trial_concierge_completed=False,
            credits=0,
            subscriptions=[],
            subscription=None,
        )

    # The last included scan is allowed with a zero internal balance.
    enforce_trial_audit_limit(_trial_user(TRIAL_SCAN_ALLOWANCE - 1))

    with pytest.raises(Exception) as refused:
        enforce_trial_audit_limit(_trial_user(TRIAL_SCAN_ALLOWANCE))
    assert getattr(refused.value, "status_code", None) == 402


# --- the support assistant prompt ------------------------------------------


def test_support_chat_prompt_is_credit_free() -> None:
    prompt = _support_prompt()
    leaks = [line for line in prompt.splitlines() if CREDIT.search(line)]
    assert leaks == [], f"the assistant would repeat credit language: {leaks}"


def test_support_chat_prompt_states_plan_allowances_in_scans() -> None:
    prompt = _support_prompt()
    for plan in METERED_PLANS:
        capabilities = CAPABILITY_MATRIX[plan]
        allowance = int(capabilities["max_audits"])
        customer_price = customer_facing_monthly_price_usd(plan)
        assert f"{allowance:,} scans/mo" in prompt, f"{plan} allowance not stated in scans"
        if is_custom_priced(plan) or customer_price is None:
            assert "Custom pricing" in prompt, f"{plan} should show custom pricing"
        else:
            assert f"USD {customer_price}/mo" in prompt, f"{plan} price drifted from the matrix"
    assert "audits/mo" not in prompt


@pytest.mark.parametrize("private_plan", sorted(PRIVATE_PLAN_IDS))
def test_support_chat_prompt_never_names_a_private_plan(private_plan: str) -> None:
    """A plan in PRIVATE_PLAN_IDS must not reach the one surface with no auth.

    Checks both the plan id and its presentation name (e.g. "Agency Trial"),
    because either form lets the model describe the plan to an anonymous caller.
    """
    prompt = _support_prompt()
    name = str(PLAN_PRESENTATION.get(private_plan, {}).get("name") or "")
    assert private_plan not in prompt
    assert name and name.lower() not in prompt.lower()
    # Guard against prose mentions that avoid the exact display name.
    generic = name.lower().replace("plan", "").strip()
    if generic:
        assert generic not in prompt.lower()


@pytest.mark.parametrize("private_plan", sorted(PRIVATE_PLAN_IDS))
def test_support_chat_fallback_reply_never_names_a_private_plan(private_plan: str) -> None:
    """The fallback reply is what an anonymous caller actually reads."""
    from routers.api_router import _build_support_chat_fallback_reply

    reply = _build_support_chat_fallback_reply("what plans do you offer?", "en")
    name = str(PLAN_PRESENTATION.get(private_plan, {}).get("name") or "")
    assert private_plan not in reply
    assert name and name.lower() not in reply.lower()
    generic = name.lower().replace("plan", "").strip()
    if generic:
        assert generic not in reply.lower()


def test_plan_summary_renders_an_unlimited_scan_allowance(monkeypatch) -> None:
    """-1 is the matrix's documented unlimited value; the customer must never
    be quoted a negative scan count such as "up to -1 scans/mo"."""
    from routers.api_router import _support_plan_summary

    monkeypatch.setitem(CAPABILITY_MATRIX["plan_executive"], "max_audits", -1)
    summary = _support_plan_summary()
    assert "unlimited scans" in summary
    assert not re.search(r"-\d", summary), summary


def test_plan_summary_lists_every_public_plan() -> None:
    """A public plan dropped by the summary would silently shrink the pricing
    answer; if config ever loses a usable figure this fails loudly instead."""
    from routers.api_router import _support_plan_summary

    summary = _support_plan_summary()
    for plan_id in PUBLIC_PLAN_TYPES:
        name = str(PLAN_PRESENTATION.get(plan_id, {}).get("name") or plan_id)
        assert name in summary, f"{plan_id} missing from the plan summary"


# --- the knowledge pack injected into that prompt --------------------------


def test_the_injected_knowledge_directory_is_not_empty() -> None:
    """A silent loss of the pack would make every sweep below vacuous."""
    assert KNOWLEDGE_FILES, f"no knowledge files under {KNOWLEDGE_DIR}"
    assert PRODUCT_KNOWLEDGE in KNOWLEDGE_FILES


@pytest.mark.parametrize("path", KNOWLEDGE_FILES, ids=lambda path: path.name)
def test_injected_knowledge_file_is_credit_free(path: Path) -> None:
    leaks = [line for line in path.read_text(encoding="utf-8").splitlines() if CREDIT.search(line)]
    assert leaks == [], f"{path.name} feeds the assistant credit language: {leaks}"


@pytest.mark.parametrize("path", KNOWLEDGE_FILES, ids=lambda path: path.name)
def test_injected_knowledge_file_promises_no_top_up_route(path: Path) -> None:
    """The deleted instruction pointed customers at a route nothing serves."""
    leaks = [line for line in path.read_text(encoding="utf-8").splitlines() if TOP_UP.search(line)]
    assert leaks == [], f"{path.name} promises a top-up flow: {leaks}"


@pytest.mark.parametrize("path", KNOWLEDGE_FILES, ids=lambda path: path.name)
def test_injected_knowledge_file_carries_no_former_brand(path: Path) -> None:
    """These files are read into answers given to Qiko customers."""
    assert not FORMER_BRAND.search(path.name), f"{path.name} is named after the former brand"
    leaks = [
        line for line in path.read_text(encoding="utf-8").splitlines() if FORMER_BRAND.search(line)
    ]
    assert leaks == [], f"{path.name} names the former brand: {leaks}"


def test_support_chat_prompt_with_the_real_domain_context_is_credit_free() -> None:
    """The whole injected surface, as the model actually receives it."""
    from services.knowledge_service import knowledge_service

    domain_context = knowledge_service.get_domain_context()
    assert "Scan Allowance" in domain_context, "the product knowledge pack is not being injected"

    prompt = build_support_chat_prompt(
        [{"role": "user", "content": "What do I get on the trial?"}],
        "en",
        domain_context=domain_context,
    )
    leaks = [line for line in prompt.splitlines() if CREDIT.search(line)]
    assert leaks == [], f"the assistant would repeat credit language: {leaks}"
    assert not TOP_UP.search(prompt)
    assert not FORMER_BRAND.search(prompt)


@pytest.mark.parametrize("path", KNOWLEDGE_FILES, ids=lambda path: path.name)
def test_injected_knowledge_file_names_no_private_plan(path: Path) -> None:
    """PRIVATE_PLAN_IDS members must not appear in text the model is shown."""
    text = path.read_text(encoding="utf-8")
    for plan_id in PRIVATE_PLAN_IDS:
        name = str(PLAN_PRESENTATION.get(plan_id, {}).get("name") or "")
        assert plan_id not in text, f"{path.name} names {plan_id}"
        assert name.lower() not in text.lower(), f"{path.name} names {name}"


@pytest.mark.parametrize("plan", PUBLIC_PLAN_TYPES)
def test_product_knowledge_plan_row_matches_the_capability_matrix(plan: str) -> None:
    """The pack states allowances in scans, and they are the matrix's numbers."""
    name = PLAN_PRESENTATION[plan]["name"]
    rows = [
        line
        for line in PRODUCT_KNOWLEDGE.read_text(encoding="utf-8").splitlines()
        if f"**{name}**" in line
    ]
    assert len(rows) == 1, f"expected one plan row for {name}, found {len(rows)}"
    row = rows[0]

    capabilities = CAPABILITY_MATRIX[plan]
    allowance = int(capabilities["max_audits"])
    sites = int(capabilities["max_sites"])
    customer_price = customer_facing_monthly_price_usd(plan)
    assert f"{allowance:,}" in row, f"{name} row does not state {allowance:,} scans"
    assert ("Unlimited" if sites < 0 else f"{sites:,}") in row, f"{name} row has the wrong sites"
    if is_custom_priced(plan) or customer_price is None:
        assert re.search(r"[Cc]ontact", row), f"{name} row should invite contact for custom pricing"
        assert "$" not in row, f"{name} row must not quote a list price"
    elif customer_price <= 0:
        assert "Free" in row, f"{name} row should state Free"
    else:
        assert f"${customer_price}/mo" in row, f"{name} row should state ${customer_price}/mo"
    assert "Scans/mo" in PRODUCT_KNOWLEDGE.read_text(encoding="utf-8")


def test_product_knowledge_does_not_advertise_withdrawn_items() -> None:
    """The product knowledge pack must not present withdrawn engines or features as available."""
    text = PRODUCT_KNOWLEDGE.read_text(encoding="utf-8")
    lines = text.splitlines()

    withdrawn_phrases = [
        "Bing",
        "Copilot",
        "Jira",
        "Slack",
        "Microsoft Teams",
        "LinkedIn",
        "Entity Authority",
        "Automations",
        "Timeline",
        "Content Hub",
        "Content Strategy",
        "Scheduled Audits",
        "dedicated strategist",
        "CMS push",
    ]
    for phrase in withdrawn_phrases:
        for line in lines:
            if phrase.lower() not in line.lower():
                continue
            if re.search(r"\bBing\b", line, re.IGNORECASE) and "Webmaster" in line:
                continue
            assert re.search(
                r"not currently (available|offered)", line, re.IGNORECASE
            ), f"{phrase} appears as available: {line.strip()}"


def test_support_chat_prompt_does_not_advertise_withdrawn_items() -> None:
    """The support prompt itself must not present withdrawn engines or features as available."""
    prompt = _support_prompt()
    lines = prompt.splitlines()

    withdrawn_phrases = [
        "Bing",
        "Copilot",
        "Jira",
        "Slack",
        "Microsoft Teams",
        "LinkedIn",
        "Entity Authority",
        "Automations",
        "Timeline",
        "Content Hub",
        "Content Strategy",
        "Scheduled Audits",
        "dedicated strategist",
        "CMS push",
    ]
    for phrase in withdrawn_phrases:
        for line in lines:
            if phrase.lower() not in line.lower():
                continue
            if re.search(r"\bBing\b", line, re.IGNORECASE) and (
                "Webmaster" in line or "Copilot/Bing" in line
            ):
                continue
            assert re.search(
                r"not currently (available|offered)", line, re.IGNORECASE
            ), f"{phrase} appears as available in support prompt: {line.strip()}"
