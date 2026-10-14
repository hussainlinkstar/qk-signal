"""Tests for the AI bot registry expansion (AEX-30).

Validates the expanded bot registry JSON and the service-level parsing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.project_bot_log_analyzer_service import (
    load_bot_registry,
    _match_bot_entry,
    _parse_registry_entry,
)


@pytest.fixture(autouse=True)
def _clear_registry_cache():
    """Clear the lru_cache before each test so JSON changes are picked up."""
    load_bot_registry.cache_clear()
    yield
    load_bot_registry.cache_clear()


def test_registry_has_21_bots():
    registry = load_bot_registry()
    assert len(registry.entries) == 21


def test_schema_version_is_3():
    registry = load_bot_registry()
    assert registry.schema_version == "3"


def test_original_bots_still_present():
    registry = load_bot_registry()
    names = {e.name for e in registry.entries}
    originals = {
        "GPTBot",
        "ChatGPT-User",
        "CCBot",
        "Google-Extended",
        "PerplexityBot",
        "Anthropic-ai",
        "Claude-Web",
    }
    assert originals.issubset(names)


def test_new_bots_present():
    registry = load_bot_registry()
    names = {e.name for e in registry.entries}
    new_bots = {
        "Applebot-Extended",
        "meta-externalagent",
        "Bytespider",
        "Amazonbot",
        "FacebookBot",
        "cohere-ai",
        "YouBot",
        "PetalBot",
        "Diffbot",
        "Timesbot",
    }
    assert new_bots.issubset(names)


@pytest.mark.parametrize(
    "ua_string,expected_bot",
    [
        ("Mozilla/5.0 (compatible; GPTBot/1.0)", "GPTBot"),
        ("Applebot-Extended/1.0", "Applebot-Extended"),
        ("Mozilla/5.0 meta-externalagent/1.0", "meta-externalagent"),
        ("Bytespider/1.0", "Bytespider"),
        ("Amazonbot/1.0", "Amazonbot"),
        ("FacebookBot/1.0", "FacebookBot"),
        ("cohere-ai", "cohere-ai"),
        ("YouBot/1.0", "YouBot"),
        ("PetalBot/2.0", "PetalBot"),
        ("Diffbot/1.0", "Diffbot"),
        ("Timesbot/1.0", "Timesbot"),
    ],
)
def test_match_bot_entry_for_new_bots(ua_string, expected_bot):
    registry = load_bot_registry()
    match = _match_bot_entry(ua_string, registry)
    assert match is not None, f"Expected to match {expected_bot} for UA '{ua_string}'"
    assert match.name == expected_bot


def test_unknown_ua_returns_none():
    registry = load_bot_registry()
    match = _match_bot_entry("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0", registry)
    assert match is None


def test_all_entries_have_category():
    registry = load_bot_registry()
    valid_categories = {"ai_training", "ai_search", "social_ai", "assistant"}
    for entry in registry.entries:
        assert (
            entry.category in valid_categories
        ), f"Bot '{entry.name}' has invalid category '{entry.category}'"


def test_timesbot_has_empty_rdns_suffixes():
    registry = load_bot_registry()
    timesbot = next(e for e in registry.entries if e.name == "Timesbot")
    assert timesbot.rdns_suffixes == ()


def test_applebot_rdns_suffix():
    registry = load_bot_registry()
    applebot = next(e for e in registry.entries if e.name == "Applebot-Extended")
    assert "applebot.apple.com" in applebot.rdns_suffixes


def test_parse_registry_entry_extracts_category():
    entry = _parse_registry_entry(
        {
            "name": "TestBot",
            "ua_contains": ["TestBot"],
            "rdns_suffixes": ["test.com"],
            "category": "ai_search",
        }
    )
    assert entry is not None
    assert entry.category == "ai_search"


def test_parse_registry_entry_defaults_category():
    entry = _parse_registry_entry(
        {
            "name": "TestBot",
            "ua_contains": ["TestBot"],
            "rdns_suffixes": [],
        }
    )
    assert entry is not None
    assert entry.category == "unknown"


# ---------------------------------------------------------------------------
# Attribution correctness: a bot registry that names the wrong bot is worse
# than no registry, because the customer acts on it.
# ---------------------------------------------------------------------------


def test_ordinary_googlebot_is_not_reported_as_ai_training_traffic():
    """Googlebot is search indexing, not AI training.

    The Google-Extended entry used to match the bare token "Googlebot", so
    every ordinary Google search crawl on every customer's site was counted
    as AI training traffic. Google-Extended is the AI-training control and is
    a separate user agent; blocking it does not affect search rankings, which
    is precisely the distinction this panel exists to show.
    """
    registry = load_bot_registry()
    match = _match_bot_entry(
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", registry
    )
    assert match is None

    extended = _match_bot_entry("Mozilla/5.0 (compatible; Google-Extended/1.0)", registry)
    assert extended is not None
    assert extended.name == "Google-Extended"
    assert extended.category == "ai_training"


def test_claudebot_is_attributed_to_claudebot_not_the_legacy_entry():
    """ClaudeBot's UA carries an @anthropic.com address.

    The legacy entry matched the bare substring "anthropic", so the real
    ClaudeBot was absorbed by it through that address and reported under a
    retired bot name.
    """
    registry = load_bot_registry()
    match = _match_bot_entry(
        "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)", registry
    )
    assert match is not None
    assert match.name == "ClaudeBot"
    assert match.category == "ai_training"


@pytest.mark.parametrize(
    "ua_string,expected_bot,expected_category",
    [
        # The bot that decides whether a site is cited in ChatGPT search.
        (
            "Mozilla/5.0 ... compatible; OAI-SearchBot/1.4; +https://openai.com/searchbot",
            "OAI-SearchBot",
            "ai_search",
        ),
        (
            "Mozilla/5.0 (compatible; Claude-SearchBot/1.0; +claudebot@anthropic.com)",
            "Claude-SearchBot",
            "ai_search",
        ),
        (
            "Mozilla/5.0 (compatible; Claude-User/1.0; +claudebot@anthropic.com)",
            "Claude-User",
            "ai_search",
        ),
    ],
)
def test_the_citation_deciding_bots_are_recognised(ua_string, expected_bot, expected_category):
    """Without these, a site cannot tell whether the engines that choose
    citations have even visited it."""
    registry = load_bot_registry()
    match = _match_bot_entry(ua_string, registry)
    assert match is not None, f"Expected {expected_bot} for UA '{ua_string}'"
    assert match.name == expected_bot
    assert match.category == expected_category


def test_openai_search_and_training_bots_stay_distinct():
    """GPTBot is training, OAI-SearchBot is search: separate opt-outs, so
    they must never collapse into one row."""
    registry = load_bot_registry()
    gptbot = _match_bot_entry("Mozilla/5.0 (compatible; GPTBot/1.4)", registry)
    searchbot = _match_bot_entry("Mozilla/5.0 (compatible; OAI-SearchBot/1.4)", registry)
    assert gptbot is not None and searchbot is not None
    assert gptbot.name != searchbot.name
    assert gptbot.category == "ai_training"
    assert searchbot.category == "ai_search"
