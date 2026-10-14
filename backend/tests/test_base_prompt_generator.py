"""SIGV2-1186: a new project gets a base prompt set covering all five types.

Before this ticket a project had only what the customer typed. If they typed
three vague prompts, four of the five search types had nothing measuring them,
every one of those cards said "unmeasured", and the product could not say what
was missing or why. These tests pin the generator itself: the catalogue is
deterministic, it always covers all five canonical types, and it degrades to
what the project actually holds instead of inventing facts about the business.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.base_prompts import (  # noqa: E402
    MAX_BASE_PROMPT_CHARS,
    BasePromptContext,
    generate_base_prompts,
    suggest_prompt_for_search_type,
)
from services.query_taxonomy import CANONICAL_SEARCH_TYPES  # noqa: E402


def _bare() -> BasePromptContext:
    """Only what every project is guaranteed to have: a name."""
    return BasePromptContext(brand="Acme")


def _rich() -> BasePromptContext:
    return BasePromptContext(
        brand="Acme",
        domain="acme.com",
        industry="dental clinic",
        market="United Kingdom",
        audience="practice managers",
        problem="patients not booking follow-up appointments",
        competitor="Globex",
    )


def test_generates_exactly_one_prompt_per_canonical_type_in_order() -> None:
    for context in (_bare(), _rich()):
        prompts = generate_base_prompts(context)
        assert [prompt.search_type for prompt in prompts] == CANONICAL_SEARCH_TYPES


def test_every_prompt_that_is_written_is_clean_and_within_the_stored_limit() -> None:
    for context in (_bare(), _rich()):
        for prompt in generate_base_prompts(context):
            assert prompt.query_text.strip() == prompt.query_text
            assert len(prompt.query_text) <= MAX_BASE_PROMPT_CHARS


def test_generated_prompts_are_unique_within_a_project() -> None:
    # The table has a unique constraint on (project_id, query_text), so a
    # catalogue that can emit the same sentence twice would fail to insert.
    # Blanks are excluded: an unwritable type yields no prompt, and two of
    # those are not a collision (SIGV2-1288).
    for context in (_bare(), _rich()):
        texts = [
            prompt.query_text.lower()
            for prompt in generate_base_prompts(context)
            if prompt.query_text
        ]
        assert len(set(texts)) == len(texts)


def test_generation_is_deterministic() -> None:
    first = [(p.search_type, p.query_text) for p in generate_base_prompts(_rich())]
    second = [(p.search_type, p.query_text) for p in generate_base_prompts(_rich())]
    assert first == second


def test_the_brand_is_named_in_the_brand_prompt() -> None:
    prompts = {p.search_type: p.query_text for p in generate_base_prompts(_rich())}
    assert "Acme" in prompts["brand"]


def test_known_industry_and_market_are_used_for_the_category_prompt() -> None:
    prompts = {p.search_type: p.query_text for p in generate_base_prompts(_rich())}
    assert "dental clinic" in prompts["category"]
    assert "United Kingdom" in prompts["category"]


def test_the_customers_own_pain_point_drives_the_problem_prompt() -> None:
    # This is Edward's "customer problem" type. When the project records what
    # the customer's buyers struggle with, the Problem prompt asks about that
    # and not about the brand.
    prompts = {p.search_type: p.query_text for p in generate_base_prompts(_rich())}
    assert "patients not booking follow-up appointments" in prompts["problem"]


def test_a_named_competitor_drives_the_comparison_prompt() -> None:
    prompts = {p.search_type: p.query_text for p in generate_base_prompts(_rich())}
    assert "Globex" in prompts["comparison"]


def test_a_bare_project_gets_the_three_prompts_that_can_honestly_be_written() -> None:
    # SIGV2-1288 replaces an earlier contract here. This used to assert five
    # prompts with "Acme" in every one, because a brand-anchored fallback was
    # judged better than a template with an empty slot.
    #
    # It is not. Brand, Feature and Comparison are brand-anchored by design:
    # the question is what the engines say about the customer. Category and
    # Problem are discovery: the question is whether an engine volunteers them
    # to somebody who has not heard of them. A prompt carrying the brand name
    # cannot measure that, because it has already supplied the answer, so the
    # score that comes back is recall of a name we handed over.
    #
    # Edward caught it on a consultancy: "This is NAMING Tessiant, the prompt
    # is what problems does it solve".
    prompts = {prompt.search_type: prompt.query_text for prompt in generate_base_prompts(_bare())}
    assert len(prompts) == 5

    for search_type in ("brand", "feature", "comparison"):
        text = prompts[search_type]
        assert "Acme" in text
        assert "{" not in text and "}" not in text
        assert "  " not in text

    # Nothing to anchor on, so nothing is written rather than something wrong.
    assert prompts["category"] == ""
    assert prompts["problem"] == ""


def test_a_discovery_prompt_never_carries_the_brand_name() -> None:
    # The rule, over every shape of context: the two discovery types either
    # ask about the category or the problem, or say nothing at all.
    contexts = (
        _bare(),
        _rich(),
        BasePromptContext(brand="Acme", industry="dental clinic"),
        BasePromptContext(brand="Acme", audience="practice managers"),
        BasePromptContext(brand="Acme", industry="dental clinic", audience="practice managers"),
        BasePromptContext(brand="Acme", problem="patients missing appointments"),
        BasePromptContext(brand="Acme", market="United Kingdom"),
    )
    for context in contexts:
        prompts = {p.search_type: p.query_text for p in generate_base_prompts(context)}
        for search_type in ("category", "problem"):
            assert "Acme" not in prompts[search_type], (search_type, prompts[search_type])


def test_an_unanchored_discovery_type_is_still_offered_as_a_fill_in_the_blank() -> None:
    # Generation does not invent, but the coverage surface must stay
    # actionable: the customer is offered a question they finish in one edit,
    # rather than one that reads as complete and measures the wrong thing.
    context = _bare()
    for search_type in ("category", "problem"):
        suggestion = suggest_prompt_for_search_type(context, search_type)
        assert suggestion
        assert "Acme" not in suggestion
        assert "[" in suggestion and "]" in suggestion


def test_long_free_text_inputs_are_trimmed_not_truncated_mid_word() -> None:
    context = BasePromptContext(
        brand="Acme",
        problem="  " + ("alpha " * 200).strip() + "  ",
    )
    problem_prompt = next(
        prompt for prompt in generate_base_prompts(context) if prompt.search_type == "problem"
    )
    assert len(problem_prompt.query_text) <= MAX_BASE_PROMPT_CHARS
    assert "  " not in problem_prompt.query_text
    assert not problem_prompt.query_text.endswith("alph?")


def test_control_characters_and_newlines_never_reach_a_prompt() -> None:
    context = BasePromptContext(brand="Ac\x00me\n\tInc", problem="line one\nline two")
    for prompt in generate_base_prompts(context):
        assert "\n" not in prompt.query_text
        assert "\t" not in prompt.query_text
        assert "\x00" not in prompt.query_text


def test_suggest_prompt_for_search_type_matches_the_generated_set() -> None:
    context = _rich()
    generated = {p.search_type: p.query_text for p in generate_base_prompts(context)}
    for search_type in CANONICAL_SEARCH_TYPES:
        assert suggest_prompt_for_search_type(context, search_type) == generated[search_type]


def test_suggest_prompt_for_an_unknown_search_type_is_none() -> None:
    assert suggest_prompt_for_search_type(_rich(), "garbage") is None
    assert suggest_prompt_for_search_type(_rich(), None) is None
