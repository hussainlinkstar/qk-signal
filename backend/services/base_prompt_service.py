"""Write a project's base prompt set and report its search-type coverage (SIGV2-1186).

``app.services.base_prompts`` decides *what* the five base prompts say. This
module is the only thing that writes them, and the only place that reads a
project's coverage of the five customer-facing search types.

Three rules it exists to enforce:

* **Nothing here may break project creation.** ``ensure_base_prompts`` never
  raises. A project is still a project if its base prompts could not be
  written; it reports why instead (``reason``) so a surface can say so.
* **The plan cap is the cap.** Base prompts are ordinary tracked prompts and
  count against ``VISIBILITY_PLAN_LIMITS`` exactly like one the customer typed.
  A locked plan gets none, and a plan with two slots left gets two, in canonical
  type order. Generating past the cap would hand out allowance nobody paid for
  and would then 402 the customer's own next prompt.
* **A generated prompt is attributable.** Every row written here carries
  ``origin="generated"`` and an explicit ``search_type``, so the customer can
  tell it from their own, change its type, or delete it.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

import models
from app.services.base_prompts import (
    ORIGIN_GENERATED,
    BasePromptContext,
    brand_from_domain,
    generate_base_prompts,
    normalize_brand,
    suggest_prompt_for_search_type,
)
from services.project_visibility_service import ProjectVisibilityService
from services.query_taxonomy import (
    CANONICAL_SEARCH_TYPES,
    resolve_search_type,
    search_type_coverage,
)

logger = logging.getLogger(__name__)

REASON_CREATED = "created"
REASON_ALREADY_COVERED = "already_covered"
REASON_PLAN_LOCKED = "plan_locked"
REASON_CAP_REACHED = "cap_reached"
REASON_NO_BRAND = "no_brand"
REASON_FAILED = "failed"


def build_base_prompt_context(
    project: models.Project,
    *,
    enrichment: dict[str, Any] | None = None,
) -> BasePromptContext | None:
    """Assemble the generator's inputs from the project, plus optional enrichment.

    Returns ``None`` when the project has no usable name, which is the only
    input every template needs.

    ``enrichment`` is the hook for a caller that already holds a classification
    of the site (``services.pre_scan_service.analyze_target`` returns
    ``category``, ``market_region`` and ``snapshot_description``). The project
    table stores none of those three, and project creation does not run a
    pre-scan, so at creation time the context is built from project fields only
    and the templates fall back accordingly. Nothing is invented to fill a gap.
    """
    # SIGV2-1288: the domain names the brand, the project name only labels the
    # container. "Tessiant website" and "Q4 test" are both real things a
    # customer calls a project, and neither is a name an AI engine has heard
    # of. Where a domain exists it wins; a project with no domain is a
    # brand-only project, where the name is the brand by construction.
    domain = getattr(project, "domain_url", None)
    brand = brand_from_domain(domain) or normalize_brand(getattr(project, "name", None))
    if brand is None:
        return None

    enrichment = enrichment if isinstance(enrichment, dict) else {}

    audience = None
    for role in list(getattr(project, "icp_roles", None) or []):
        if isinstance(role, str) and role.strip():
            audience = role.strip()
            break

    competitor = None
    for row in list(getattr(project, "competitors", None) or []):
        label = getattr(row, "display_name", None)
        if isinstance(label, str) and label.strip():
            competitor = label.strip()
            break
    if competitor is None:
        for entry in list(getattr(project, "competitors_json", None) or []):
            if isinstance(entry, str) and entry.strip():
                competitor = entry.strip()
                break

    return BasePromptContext(
        brand=brand,
        domain=domain,
        industry=enrichment.get("category") or enrichment.get("industry"),
        # Only a human-readable market is usable in prompt text; the project's
        # own target_country is an ISO alpha-2 code ("GB"), which reads as a bug
        # inside a question, so it is deliberately not substituted here.
        market=enrichment.get("market_region") or enrichment.get("market"),
        description=enrichment.get("snapshot_description") or enrichment.get("description"),
        audience=audience,
        problem=getattr(project, "pain_points", None),
        competitor=competitor,
    )


def resolve_query_search_type(visibility_query: models.ProjectVisibilityQuery) -> str:
    """The canonical search type of one prompt: stored first, inference second."""
    return resolve_search_type(
        stored=getattr(visibility_query, "search_type", None),
        raw_query=visibility_query.query_text,
    )


def build_coverage(
    db: Session,
    *,
    project: models.Project,
    enrichment: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search-type coverage for a project, with a suggestion for each gap.

    One entry per canonical search type, in canonical order, shaped
    ``{id, label, premium, prompt_count, covered, suggested_prompt}``.
    ``suggested_prompt`` is the sentence the generator would write for an
    uncovered type and ``None`` for a covered one, so the surface can offer the
    gap as something to fill rather than only naming it.

    Coverage counts **active** prompts only: a deactivated prompt measures
    nothing, so counting it would claim coverage the next scan will not deliver.
    """
    service = ProjectVisibilityService(db)
    active_queries = service.list_queries(project_id=project.id, include_inactive=False)
    coverage = search_type_coverage(
        resolve_query_search_type(visibility_query) for visibility_query in active_queries
    )

    context = build_base_prompt_context(project, enrichment=enrichment)
    for entry in coverage:
        entry["suggested_prompt"] = (
            None
            if entry["covered"] or context is None
            else suggest_prompt_for_search_type(context, entry["id"])
        )
    return coverage


def ensure_base_prompts(
    db: Session,
    *,
    project: models.Project,
    enrichment: dict[str, Any] | None = None,
    request_refresh: bool = True,
) -> dict[str, Any]:
    """Create one base prompt for every search type the project does not cover.

    Idempotent: a type that already has an active prompt is left alone, and a
    prompt whose exact text already exists on the project is never duplicated
    (the table has a unique constraint on ``(project_id, query_text)``).
    Re-running this adds nothing once the five types are covered, which is what
    makes it safe to call from more than one path.

    Returns ``{"created": [...], "reason": ..., "coverage": [...]}``. Never
    raises: project creation calls this, and a failure to write base prompts
    must not fail the project. Any unexpected error is logged, the transaction
    is rolled back, and ``reason`` is ``"failed"``.

    ``request_refresh`` enqueues one coalesced, unbilled visibility refresh for
    the project when prompts were created, which is the same thing adding a
    prompt by hand does (SIGV2-1182). It moves work the hourly sweep would have
    done anyway rather than adding any, so the cost is unchanged; it is a flag
    only so a caller writing many projects at once can decline it.
    """
    created: list[models.ProjectVisibilityQuery] = []
    try:
        context = build_base_prompt_context(project, enrichment=enrichment)
        if context is None:
            return {
                "created": [],
                "reason": REASON_NO_BRAND,
                "coverage": build_coverage(db, project=project, enrichment=enrichment),
            }

        service = ProjectVisibilityService(db)
        entitlements = service.resolve_entitlements(project)
        max_queries = int(entitlements["max_queries"])
        allowed_providers = list(entitlements["allowed_providers"])

        all_queries = service.list_queries(project_id=project.id, include_inactive=True)
        active_queries = [query for query in all_queries if query.is_active]
        covered = {resolve_query_search_type(query) for query in active_queries}
        existing_text_keys = {
            " ".join(str(query.query_text or "").split()).lower() for query in all_queries
        }

        if max_queries <= 0:
            return {
                "created": [],
                "reason": REASON_PLAN_LOCKED,
                "coverage": build_coverage(db, project=project, enrichment=enrichment),
            }

        missing = [
            search_type for search_type in CANONICAL_SEARCH_TYPES if search_type not in covered
        ]
        if not missing:
            return {
                "created": [],
                "reason": REASON_ALREADY_COVERED,
                "coverage": build_coverage(db, project=project, enrichment=enrichment),
            }

        # One provider per generated prompt: the first the plan allows, matching
        # what create_query does for a prompt submitted with no provider
        # selection. More engines per prompt is the customer's choice, not ours
        # to make on their behalf. ``allowed_providers`` already arrives in the
        # canonical SUPPORTED_VISIBILITY_PROVIDERS order.
        providers = allowed_providers[:1]

        active_count = len(active_queries)
        by_type = {prompt.search_type: prompt for prompt in generate_base_prompts(context)}
        cap_reached = False
        for search_type in missing:
            if active_count >= max_queries:
                cap_reached = True
                break
            prompt = by_type.get(search_type)
            if prompt is None or not prompt.query_text:
                continue
            text_key = " ".join(prompt.query_text.split()).lower()
            if text_key in existing_text_keys:
                continue

            row = models.ProjectVisibilityQuery(
                project_id=project.id,
                query_text=prompt.query_text,
                # The internal aeo/geo lane keeps its existing default; the
                # customer-facing type is the new explicit column.
                query_type="aeo",
                search_type=search_type,
                origin=ORIGIN_GENERATED,
                providers=list(providers),
                is_active=True,
            )
            db.add(row)
            created.append(row)
            existing_text_keys.add(text_key)
            active_count += 1

        if created:
            db.commit()
            for row in created:
                db.refresh(row)
            if request_refresh:
                service.request_visibility_refresh(project)

        if created:
            reason = REASON_CREATED
        elif cap_reached:
            reason = REASON_CAP_REACHED
        else:
            # Every missing type's suggested text already exists on the project
            # as an inactive prompt, so there is nothing to add that would not
            # collide with a row the customer can simply reactivate.
            reason = REASON_ALREADY_COVERED

        return {
            "created": created,
            "reason": reason,
            "coverage": build_coverage(db, project=project, enrichment=enrichment),
        }
    except Exception:
        logger.exception(
            "ensure_base_prompts failed for project_id=%s", getattr(project, "id", None)
        )
        try:
            db.rollback()
        except Exception:
            logger.exception("ensure_base_prompts rollback failed")
        return {"created": [], "reason": REASON_FAILED, "coverage": []}
