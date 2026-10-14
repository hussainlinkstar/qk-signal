#!/usr/bin/env python3
"""Stdio-to-remote bridge for the Qiko Signal MCP server (SIGV2-1210).

Some MCP clients only speak stdio. The Signal MCP server is hosted and speaks
Streamable HTTP, so this script sits between them: it reads newline-delimited
JSON-RPC from stdin, posts each message to the remote endpoint with the API
key, and writes the reply to stdout.

It deliberately holds **no logic**. It does not know what tools exist, which
scopes they need, what a plan is entitled to, or which call costs money. Every
one of those decisions is made server-side and is reached identically whether
a client connects directly or through here. Two implementations of the same
rules is how they drift, and a bridge that enforced anything would be the
second implementation.

What it therefore does not do, on purpose:

* no retries. A retry of ``signal_run_audit`` is a retry of a paid operation,
  and the server's idempotency window is what makes that safe; a retry loop
  here would be a second, dumber policy layer in front of it.
* no response rewriting, so a refusal reaches the client with the wording and
  the ``data.retryable`` flag the server chose.
* no caching, so it cannot serve a stale answer about a live audit.

Usage, from a client's MCP server configuration:

    command: python3
    args: ["/path/to/mcp_stdio_bridge.py"]
    env:
      QIKO_SIGNAL_API_KEY: "stx_live_..."

Only the key is required. The endpoint defaults to production, which is the
host the overwhelming majority of customers want and the one the Developer
Hub already prints in every sample it hands out: that page builds its base
from NEXT_PUBLIC_APP_URL falling back to https://qiko.ai/signal and appends
/api/v1, so this default is the same base with /mcp on the end rather than a
second answer to the same question.

Point it somewhere else, at preprod or a local stack, with
QIKO_SIGNAL_MCP_URL:

    env:
      QIKO_SIGNAL_MCP_URL: "https://signal.preprod.qiko.ai/api/v1/mcp"
      QIKO_SIGNAL_API_KEY: "stx_test_..."
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 120
# A JSON-RPC internal error, used only for failures of this bridge itself.
JSONRPC_INTERNAL_ERROR = -32603

# Production. Derived from the same base the Developer Hub prints in the code
# samples customers copy (frontend/src/app/(app)/dashboard/developer/content.ts
# builds it from NEXT_PUBLIC_APP_URL with this fallback, then appends /api/v1),
# so the hosted endpoint has one answer rather than two that can drift apart.
# A wrong value here posts a live API key at whatever host answers, which is
# why it is pinned by a test rather than left to a reader's memory.
DEFAULT_MCP_URL = "https://qiko.ai/signal/api/v1/mcp"


def _fail(message: str) -> "None":
    sys.stderr.write(f"qiko-signal-mcp-bridge: {message}\n")
    raise SystemExit(2)


def _config() -> tuple[str, str]:
    url = (os.environ.get("QIKO_SIGNAL_MCP_URL") or "").strip() or DEFAULT_MCP_URL
    key = (os.environ.get("QIKO_SIGNAL_API_KEY") or "").strip()
    if not key:
        _fail("QIKO_SIGNAL_API_KEY is not set")
    if not url.startswith("https://") and not url.startswith("http://localhost"):
        # The key is a bearer credential, so it does not travel in cleartext.
        # Plain-HTTP localhost stays allowed for development against a local
        # stack, which is the one case where there is no network to sniff.
        _fail("QIKO_SIGNAL_MCP_URL must be https (http is allowed only for localhost)")
    return url, key


def _forward(
    url: str, key: str, payload: bytes, protocol_version: str | None
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=payload, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    # Sent as X-API-Key rather than Authorization because the server accepts
    # either and this one cannot be confused with an OAuth token.
    request.add_header("X-API-Key", key)
    if protocol_version:
        request.add_header("MCP-Protocol-Version", protocol_version)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        # The server's error body is passed through untouched: it carries the
        # refusal the client needs to read, including whether to retry.
        return exc.code, exc.read() or b""
    except urllib.error.URLError as exc:
        return 0, json.dumps({"transport_error": str(exc.reason)}).encode("utf-8")


def _write(message: object) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    url, key = _config()
    # Remembered from the initialize result so later requests declare the
    # revision the server actually negotiated.
    protocol_version: str | None = None

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Malformed JSON from the client.",
                    },
                }
            )
            continue

        request_id = message.get("id") if isinstance(message, dict) else None
        status, body = _forward(url, key, line.encode("utf-8"), protocol_version)

        # A notification is acknowledged with 202 and no body, and a
        # notification expects no reply, so nothing is written.
        if status == 202 or not body:
            continue

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": JSONRPC_INTERNAL_ERROR,
                        "message": f"The MCP endpoint returned a non-JSON response (HTTP {status}).",
                    },
                }
            )
            continue

        # An HTTP-level refusal (auth, plan gate, rate limit) is not a JSON-RPC
        # envelope, so it is wrapped into one rather than dropped: a stdio
        # client has no other way to see it.
        if isinstance(parsed, dict) and "jsonrpc" not in parsed and "error" in parsed:
            detail = parsed["error"]
            wrapped = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": JSONRPC_INTERNAL_ERROR,
                    "message": detail.get(
                        "message", f"The request was refused (HTTP {status})."
                    ),
                    "data": detail,
                },
            }
            _write(wrapped)
            continue

        if isinstance(parsed, dict):
            negotiated = (parsed.get("result") or {}).get("protocolVersion")
            if isinstance(negotiated, str) and negotiated:
                protocol_version = negotiated

        # Objects and batch arrays alike are passed through unchanged.
        _write(parsed)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
