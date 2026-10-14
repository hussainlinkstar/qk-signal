"""The stdio bridge's default endpoint (SIGV2-1210).

This file exists for one assertion that is worth a file: the bridge posts a
customer's live API key to whatever URL it resolves, so a wrong default is a
credential leak to a third party, not a 404. The default therefore cannot be
a string a reader is trusted to keep correct.

It is pinned twice. Once literally, so a careless edit fails loudly, and once
against the Developer Hub's own base, which is where customers read the
hosted API address from. The second is the one that catches real drift: if
the product ever moves off `qiko.ai/signal`, the Hub constant moves with it
and this test fails until the bridge follows.

The bridge lives at `scripts/` in the repository root rather than under
`backend/`, but `pytest backend/tests` is the only suite CI runs, so its test
lives here and loads it by path.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_PATH = REPO_ROOT / "scripts" / "mcp_stdio_bridge.py"
DEVELOPER_HUB_CONTENT = (
    REPO_ROOT / "frontend" / "src" / "app" / "(app)" / "dashboard" / "developer" / "content.ts"
)


def _load_bridge():
    spec = importlib.util.spec_from_file_location("qiko_mcp_stdio_bridge", BRIDGE_PATH)
    assert spec and spec.loader, f"could not load the bridge from {BRIDGE_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge = _load_bridge()


@pytest.fixture(autouse=True)
def _clean_bridge_env(monkeypatch):
    """No ambient configuration: an operator shell must not decide the result."""
    monkeypatch.delenv("QIKO_SIGNAL_MCP_URL", raising=False)
    monkeypatch.delenv("QIKO_SIGNAL_API_KEY", raising=False)


def test_default_url_is_the_production_mcp_endpoint():
    assert bridge.DEFAULT_MCP_URL == "https://qiko.ai/signal/api/v1/mcp"


def test_default_url_matches_the_base_the_developer_hub_publishes():
    """One answer for the hosted address, not two that can drift apart.

    The Hub builds `API_BASE_URL` from `NEXT_PUBLIC_APP_URL` with a hardcoded
    fallback and appends `/api/v1`; that fallback is what an unconfigured
    reader sees, and it is what the bridge's unconfigured default must agree
    with.
    """
    source = DEVELOPER_HUB_CONTENT.read_text(encoding="utf-8")
    match = re.search(
        r"const API_BASE_URL\s*=\s*`\$\{\(process\.env\.NEXT_PUBLIC_APP_URL\s*\|\|\s*"
        r'"(?P<fallback>[^"]+)"\)',
        source,
    )
    assert match, (
        "could not read the Developer Hub's API base fallback from "
        f"{DEVELOPER_HUB_CONTENT}; if that constant was restructured, re-derive "
        "the bridge default from its new shape rather than deleting this test"
    )
    hub_base = match.group("fallback").rstrip("/")

    assert bridge.DEFAULT_MCP_URL == f"{hub_base}/api/v1/mcp"


def test_config_falls_back_to_the_default_when_the_override_is_unset(monkeypatch):
    monkeypatch.setenv("QIKO_SIGNAL_API_KEY", "stx_live_example")

    url, key = bridge._config()

    assert url == bridge.DEFAULT_MCP_URL
    assert key == "stx_live_example"


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_override_is_treated_as_unset(monkeypatch, blank):
    """An empty variable is a client config that set nothing, not an empty host."""
    monkeypatch.setenv("QIKO_SIGNAL_MCP_URL", blank)
    monkeypatch.setenv("QIKO_SIGNAL_API_KEY", "stx_live_example")

    url, _ = bridge._config()

    assert url == bridge.DEFAULT_MCP_URL


def test_the_override_still_wins_for_preprod(monkeypatch):
    monkeypatch.setenv("QIKO_SIGNAL_MCP_URL", "https://signal.preprod.qiko.ai/api/v1/mcp")
    monkeypatch.setenv("QIKO_SIGNAL_API_KEY", "stx_test_example")

    url, key = bridge._config()

    assert url == "https://signal.preprod.qiko.ai/api/v1/mcp"
    assert key == "stx_test_example"


def test_a_plaintext_override_is_still_refused(monkeypatch):
    """The default being safe must not relax the check on what replaces it."""
    monkeypatch.setenv("QIKO_SIGNAL_MCP_URL", "http://signal.example.com/api/v1/mcp")
    monkeypatch.setenv("QIKO_SIGNAL_API_KEY", "stx_live_example")

    with pytest.raises(SystemExit) as excinfo:
        bridge._config()

    assert excinfo.value.code == 2


def test_localhost_over_plain_http_stays_allowed(monkeypatch):
    monkeypatch.setenv("QIKO_SIGNAL_MCP_URL", "http://localhost:8000/api/v1/mcp")
    monkeypatch.setenv("QIKO_SIGNAL_API_KEY", "stx_test_example")

    url, _ = bridge._config()

    assert url == "http://localhost:8000/api/v1/mcp"


def test_a_missing_key_still_fails_even_though_the_url_now_defaults(monkeypatch):
    """The default supplies a host, never a credential."""
    with pytest.raises(SystemExit) as excinfo:
        bridge._config()

    assert excinfo.value.code == 2
