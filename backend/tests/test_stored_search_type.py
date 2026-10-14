"""SIGV2-1186: a prompt's stored search type beats the text-based inference.

Before this ticket a prompt had no search type of its own. Scoring recovered one
by running :func:`classify_query_category` over the prompt's own words and
collapsing the result with :func:`to_canonical`, whose documented default for
anything unrecognised is ``category``. Edward's objection is exactly that: a
customer who never wrote anything resembling a "customer problem" question had
the Problem type silently reported as unmeasured, and nothing in the product
said why.

The type is now a stored property of the prompt. The text-based classifier is
kept, demoted to a *suggestion* used to pre-fill the field, and the stored value
is what every scoring path reads. These tests pin that precedence, including the
case that matters most: a stored type the inference would never have guessed.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.query_taxonomy import (  # noqa: E402
    CANONICAL_SEARCH_TYPES,
    SEARCH_TYPE_SOURCE_INFERRED,
    SEARCH_TYPE_SOURCE_STORED,
    normalize_search_type,
    resolve_search_type,
    search_type_coverage,
    search_type_source,
    suggest_search_type,
)


def test_normalize_search_type_accepts_canonical_ids_and_rejects_noise() -> None:
    for search_type in CANONICAL_SEARCH_TYPES:
        assert normalize_search_type(search_type) == search_type
        assert normalize_search_type(f"  {search_type.upper()} ") == search_type
    for rejected in (None, "", "   ", "aeo", "geo", "other", "garbage", 7, True):
        assert normalize_search_type(rejected) is None


def test_suggest_search_type_is_the_old_text_inference() -> None:
    # Unchanged behaviour of classify_query_category + to_canonical, now named
    # for what it is: a suggestion, not a measurement of the customer's intent.
    assert suggest_search_type("acme vs globex") == "comparison"
    assert suggest_search_type("how much does acme cost") == "feature"
    assert suggest_search_type("how to migrate to acme") == "problem"
    assert suggest_search_type("why does onboarding fail") == "problem"
    # The documented safe default for anything the patterns do not recognise.
    assert suggest_search_type("acme") == "category"
    assert suggest_search_type(None) == "category"


def test_stored_search_type_wins_over_the_text_inference() -> None:
    # The whole point of the ticket. The text says nothing about a customer
    # problem, so the inference would file it under Category; the customer (or
    # the base-prompt generator) declared Problem, and that is what scoring
    # must read.
    assert suggest_search_type("acme for dental clinics") == "category"
    assert resolve_search_type(stored="problem", raw_query="acme for dental clinics") == "problem"
    # ... and the reverse direction, so this is precedence and not a constant.
    assert suggest_search_type("acme vs globex") == "comparison"
    assert resolve_search_type(stored="brand", raw_query="acme vs globex") == "brand"


def test_resolve_falls_back_to_inference_when_nothing_is_stored() -> None:
    # Every prompt written before this migration has search_type NULL, so the
    # old answer has to keep coming out of the same function.
    assert resolve_search_type(stored=None, raw_query="acme vs globex") == "comparison"
    assert resolve_search_type(stored="", raw_query="how much does acme cost") == "feature"
    assert resolve_search_type(stored="garbage", raw_query="acme") == "category"


def test_resolve_search_type_is_total() -> None:
    for stored in (None, "", "garbage", "brand"):
        for raw_query in (None, "", "acme vs globex", "how to do a thing"):
            assert resolve_search_type(stored=stored, raw_query=raw_query) in CANONICAL_SEARCH_TYPES


def test_search_type_source_distinguishes_stored_from_inferred() -> None:
    assert search_type_source("problem") == SEARCH_TYPE_SOURCE_STORED
    assert search_type_source(None) == SEARCH_TYPE_SOURCE_INFERRED
    assert search_type_source("garbage") == SEARCH_TYPE_SOURCE_INFERRED


def test_search_type_coverage_reports_all_five_in_order() -> None:
    coverage = search_type_coverage(["brand", "brand", "problem"])
    assert [entry["id"] for entry in coverage] == CANONICAL_SEARCH_TYPES
    by_id = {entry["id"]: entry for entry in coverage}
    assert by_id["brand"]["prompt_count"] == 2
    assert by_id["brand"]["covered"] is True
    assert by_id["problem"]["prompt_count"] == 1
    assert by_id["problem"]["covered"] is True
    for uncovered in ("category", "feature", "comparison"):
        assert by_id[uncovered]["prompt_count"] == 0
        assert by_id[uncovered]["covered"] is False
    assert by_id["comparison"]["premium"] is True
    assert by_id["brand"]["premium"] is False


def test_search_type_coverage_of_nothing_is_five_gaps() -> None:
    coverage = search_type_coverage([])
    assert len(coverage) == 5
    assert all(entry["covered"] is False for entry in coverage)
    assert all(entry["prompt_count"] == 0 for entry in coverage)
