"""SIGV2-1251: the advisor-chat timeout must bound real work, and session
revocation during account deletion must not report failure as success.

Two independent findings from the same bug-hunt pass:

a) ``advisor_chat`` wrapped the sync LLM call in a per-request
   ``ThreadPoolExecutor`` used as a context manager. ``__exit__`` calls
   ``shutdown(wait=True)``, so the request blocked until the LLM call finished
   regardless of ``future.result(timeout=...)``, and repeated timeouts piled up
   threads. The call now runs on a shared, bounded executor behind a
   non-blocking capacity gate, and the advisor's Bedrock invocation carries a
   socket read timeout so a timed-out call stops consuming LLM resources
   instead of running to completion in the background.

b) ``delete_user_data`` used to call ``asyncio.run(revoke_session_jti(...))``
   once per JTI and count every iteration as a success. SIGV2-1240 replaced
   that with a single ``revoke_session_jtis`` call that counts only confirmed
   revocations; what remained was that a *partial* failure was invisible to the
   caller (``revoked_sessions`` alone cannot be compared against anything). The
   outcome is now logged at ERROR and surfaced on the response.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import os
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import routers.api_router as api_router_module
from middleware import session_checker
from tests.test_user_data_export_delete_flow import _build_workspace_client, _delete


# --------------------------------------------------------------------------
# (a) advisor chat timeout
# --------------------------------------------------------------------------


def _advisor_report() -> dict:
    return {"summary": "ok"}


def test_timed_out_advisor_call_returns_promptly_without_waiting_for_the_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard must bound the REQUEST, not just the future.

    On the old code the surrounding ``with ThreadPoolExecutor(...)`` block
    blocked on shutdown until the slow call finished, so this took as long as
    the LLM call itself.
    """
    monkeypatch.setattr(api_router_module, "_ADVISOR_CHAT_TIMEOUT_SECONDS", 0.1, raising=True)

    started = threading.Event()

    def _slow_answer(_report, _message, _history):
        started.set()
        time.sleep(3.0)
        return {"reply": "too late", "citations": []}

    monkeypatch.setattr(
        api_router_module.advisor_chat_service, "answer", _slow_answer, raising=True
    )

    begin = time.monotonic()
    with pytest.raises(TimeoutError):
        api_router_module._run_advisor_chat_with_timeout(_advisor_report(), "hello", [])
    elapsed = time.monotonic() - begin

    assert started.is_set(), "the call should have been dispatched"
    # Generous bound: the point is that it is nowhere near the 3s sleep.
    assert elapsed < 1.5, f"request blocked for {elapsed:.2f}s waiting on the LLM call"


def test_concurrent_advisor_calls_are_bounded_and_threads_do_not_pile_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated timeouts must not accumulate unbounded in-flight LLM calls."""
    cap = api_router_module._ADVISOR_CHAT_MAX_CONCURRENCY
    monkeypatch.setattr(api_router_module, "_ADVISOR_CHAT_TIMEOUT_SECONDS", 0.1, raising=True)

    lock = threading.Lock()
    in_flight = 0
    peak = 0
    release = threading.Event()

    def _blocking_answer(_report, _message, _history):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        try:
            release.wait(timeout=10)
            return {"reply": "ok", "citations": []}
        finally:
            with lock:
                in_flight -= 1

    monkeypatch.setattr(
        api_router_module.advisor_chat_service, "answer", _blocking_answer, raising=True
    )

    # Fire well past the cap. Every one of these times out at 0.1s.
    attempts = cap * 4
    rejected = 0
    for _ in range(attempts):
        try:
            api_router_module._run_advisor_chat_with_timeout(_advisor_report(), "hi", [])
        except api_router_module.AdvisorChatCapacityError:
            rejected += 1
        except TimeoutError:
            pass

    try:
        assert peak <= cap, f"{peak} concurrent LLM calls exceeded the cap of {cap}"
        # Once the cap is saturated by stuck calls, further attempts are
        # refused outright rather than queued behind them.
        assert rejected > 0, "expected the capacity gate to refuse work once saturated"
        assert (
            threading.active_count() < cap + 50
        ), "worker threads accumulated beyond the bounded pool"
    finally:
        release.set()


def test_advisor_chat_capacity_refusal_degrades_to_a_safe_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capacity refusal is a safe fallback reply, not a 500."""

    def _raise_capacity(_report, _message, _history):
        raise api_router_module.AdvisorChatCapacityError("busy")

    monkeypatch.setattr(
        api_router_module, "_run_advisor_chat_with_timeout", _raise_capacity, raising=True
    )

    result = api_router_module._advisor_chat_result_or_fallback(_advisor_report(), "hi", [], 1)

    assert result["citations"] == []
    assert "couldn't analyse that right now" in result["reply"]


def test_advisor_bedrock_call_carries_a_socket_read_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The LLM call itself must be abortable, not merely abandoned.

    Acceptance: "a timed-out advisor chat call does not continue consuming LLM
    resources in the background". A thread cannot be force-killed, so the
    invocation gets a socket read timeout instead.
    """
    from services import advisor_chat_service

    captured: dict = {}

    def _fake_generate(system, user_prompt, **kwargs):
        captured.update(kwargs)
        return '{"reply": "ok", "citations": []}'

    monkeypatch.setattr("core.bedrock_text.bedrock_available", lambda: True, raising=True)
    monkeypatch.setattr("core.bedrock_text.bedrock_generate_text", _fake_generate, raising=True)

    advisor_chat_service.answer(_advisor_report(), "hello", [])

    assert captured.get("read_timeout") is not None, "advisor call has no socket read timeout"
    # Within the 5s interactive budget (AGENTS 8.7 Chat API).
    assert 0 < captured["read_timeout"] <= 5.0
    # One attempt only: botocore retries would multiply the wall clock past the
    # interactive guard.
    assert captured.get("max_attempts") == 1


def test_bedrock_client_factory_defaults_are_unchanged_and_timeouts_are_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The long-running audit/debate paths must keep boto3's defaults."""
    from core import bedrock_runtime

    calls: list[dict] = []

    class _FakeBoto3:
        @staticmethod
        def client(name, **kwargs):
            calls.append(kwargs)
            return object()

    monkeypatch.setitem(sys.modules, "boto3", _FakeBoto3)

    bedrock_runtime.create_bedrock_runtime_client()
    assert "config" not in calls[-1], "default client must not impose a timeout config"

    bedrock_runtime.create_bedrock_runtime_client(read_timeout=4.0, max_attempts=1)
    config = calls[-1].get("config")
    assert config is not None
    assert config.read_timeout == 4.0
    assert config.retries["max_attempts"] == 1


# --------------------------------------------------------------------------
# (b) session revocation on account deletion
# --------------------------------------------------------------------------


def test_revoke_session_jtis_counts_only_confirmed_revocations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The count the deletion response reports must be honest.

    ``delete_user_data`` derives its failure count from this number, so a
    helper that counted attempts instead of successes would silently inflate
    ``revoked_sessions`` and hide a Redis outage again.
    """
    outcomes = {"a": True, "b": False, "c": True}

    async def _revoke(jti, *_args, **_kwargs):
        return outcomes[jti]

    monkeypatch.setattr(session_checker, "revoke_session_jti", _revoke, raising=True)

    assert asyncio.run(session_checker.revoke_session_jtis(["a", "b", "c"])) == 2


class _AsyncioProxy:
    """Stand-in for the ``asyncio`` module that counts ``run`` calls.

    Injected into the router's namespace only, so the test counts the router's
    own event loops and not the ones the test client runs internally.
    """

    def __init__(self) -> None:
        self.run_calls = 0

    def __getattr__(self, name):
        return getattr(asyncio, name)

    def run(self, coro, **kwargs):
        self.run_calls += 1
        return asyncio.run(coro, **kwargs)


def _add_member_sessions(db, member, count: int) -> None:
    """Extra JTIs so a per-JTI event loop is actually distinguishable."""
    import models

    db.add_all(
        [
            models.UserSession(
                user_id=member.id,
                token_jti=f"member-extra-jti-{index}",
                is_active=True,
                expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            )
            for index in range(count)
        ]
    )
    db.commit()


def test_account_deletion_revokes_every_session_on_one_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One loop for all JTIs, not ``asyncio.run`` per JTI."""
    loops: list[int] = []
    proxy = _AsyncioProxy()
    monkeypatch.setattr(api_router_module, "asyncio", proxy, raising=True)

    async def _record(jti, *_args, **_kwargs):
        loops.append(id(asyncio.get_running_loop()))
        return True

    monkeypatch.setattr(session_checker, "revoke_session_jti", _record, raising=True)

    for client, db, _owner, member, *_ in _build_workspace_client(actor="member"):
        _add_member_sessions(db, member, 4)

        response = _delete(client)

        assert response.status_code == 200
        assert len(loops) == 5, f"expected 5 revocations, saw {len(loops)}"
        assert len(set(loops)) == 1, "revocations ran on more than one event loop"
        assert (
            proxy.run_calls == 1
        ), f"the router opened {proxy.run_calls} event loops; expected a single one"
        body = response.json()
        assert body["revoked_sessions"] == 5
        assert body["failed_session_revocations"] == 0
        assert body["session_revocation_complete"] is True


def test_failed_session_revocation_is_logged_and_surfaced_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing revocation must not be reported as a complete success."""

    async def _fail(_jti, *_args, **_kwargs):
        return False

    monkeypatch.setattr(session_checker, "revoke_session_jti", _fail, raising=True)

    for client, _db, _owner, _member, *_ in _build_workspace_client(actor="member"):
        with caplog.at_level(logging.ERROR):
            response = _delete(client)

        # Deletion itself still succeeds: the user rows are already gone.
        assert response.status_code == 200
        body = response.json()

        assert body["revoked_sessions"] == 0
        assert body["failed_session_revocations"] >= 1
        assert body["session_revocation_complete"] is False

        errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
        assert any("revoke" in m.lower() for m in errors), "failure was not logged at ERROR"


def test_revocation_exception_is_counted_as_failure_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising Redis client must not turn a completed deletion into a 500."""

    async def _raise(_jti, *_args, **_kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(session_checker, "revoke_session_jti", _raise, raising=True)

    for client, _db, _owner, _member, *_ in _build_workspace_client(actor="member"):
        response = _delete(client)

        assert response.status_code == 200
        body = response.json()
        assert body["revoked_sessions"] == 0
        assert body["failed_session_revocations"] >= 1
        assert body["session_revocation_complete"] is False
