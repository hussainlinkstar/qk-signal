"""Shared pytest configuration for backend test suite."""

from __future__ import annotations

import os

# Defensive AWS env defaults set at import time, before any app/boto3 import, to
# prevent AWS IMDS credential-resolution retries from hanging the test process.
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")

# Test-only secrets, set before any app import so core.config.settings picks
# them up. Without these, anything touching JWT issuance/verification or
# encrypted columns (core/encrypted_types.py) raises "Set
# OAUTH_TOKEN_ENCRYPTION_KEY before using encrypted columns" or similar,
# since core.config has no non-empty default for any of them (correctly, in
# production none of these should ever have a source-controlled default).
# SIGNAL-1012: this was missing entirely, causing 46 tests to fail in both CI
# and any fresh local checkout. Fixed, distinct, and 32+ chars only to satisfy
# the app's own "not a placeholder" / minimum-length checks, never used
# outside the test process.
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-not-for-production-use-32chars")
os.environ.setdefault("SESSION_SECRET_KEY", "test-session-secret-key-not-for-production-use-32c")
os.environ.setdefault(
    "OAUTH_TOKEN_ENCRYPTION_KEY", "test-oauth-token-encryption-key-not-for-prod-32ch"
)

# Test-only custom-domain CNAME target. Production has no built-in default for
# this value (unset disables the feature); the suite configures an explicit
# placeholder instead, and tests covering the unconfigured state override the
# settings attribute directly.
os.environ.setdefault("CUSTOM_DOMAIN_CNAME_TARGET", "test-custom-domains.example")

import contextlib
import fnmatch

import pytest


class _InMemoryAsyncRedis:
    """Minimal dict-backed async Redis stand-in for the test suite.

    Only the commands exercised by auth request paths are implemented;
    anything else raises AttributeError, which the same ``except`` blocks
    that used to swallow connection errors still catch, so behavior for
    uncovered commands is unchanged from the previous no-Redis environment.
    """

    def __init__(self, store: dict | None = None):
        self._store: dict = {} if store is None else store
        self._ttls: dict = {}

    async def exists(self, *keys):
        return sum(1 for k in keys if k in self._store)

    async def setex(self, key, _ttl, value):
        self._store[key] = value
        self._ttls[key] = _ttl
        return True

    async def set(self, key, value, ex=None, nx=False, xx=False):
        if nx and key in self._store:
            return None
        if xx and key not in self._store:
            return None
        self._store[key] = value
        if ex is not None:
            self._ttls[key] = ex
        return True

    async def get(self, key):
        return self._store.get(key)

    async def getdel(self, key):
        return self._store.pop(key, None)

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            removed += 1 if self._store.pop(key, None) is not None else 0
            self._ttls.pop(key, None)
        return removed

    async def incr(self, key):
        self._store[key] = int(self._store.get(key, 0)) + 1
        return self._store[key]

    async def expire(self, _key, _ttl):
        self._ttls[_key] = _ttl
        return True

    async def ttl(self, key):
        return self._ttls.get(key, -1)

    def scan_iter(self, match=None):
        keys = (
            list(self._store)
            if match is None
            else [k for k in self._store if fnmatch.fnmatch(k, match)]
        )

        async def _gen():
            for key in keys:
                yield key

        return _gen()


@pytest.fixture(autouse=True)
def _in_memory_redis(monkeypatch):
    """Give auth's Redis-dependent paths a working in-memory Redis.

    The refresh-token denylist check and the session-revocation middleware
    fail closed on Redis errors (SIGV2-1242) and the login rate limiter now
    lives on Redis (SIGV2-1243), so tests exercising authenticated requests
    and logins need a functional stand-in on those modules instead of relying
    on the old fail-open or per-process paths. Other modules keep the
    previous no-Redis behavior. Tests simulating an outage override the same
    attributes with their own monkeypatch, which wins because it runs after
    this fixture.

    ``auth.mfa`` is included because its replay guard is fail-closed
    (SIGV2-1244) and SIGV2-1258 put the MFA management endpoints behind it, so
    without a stand-in every TOTP-verifying request answers 503.
    """
    import auth.mfa as mfa_module
    import middleware.rate_limiter as rate_limiter_module
    import middleware.session_checker as session_checker_module
    import routers.auth as auth_router_module

    client = _InMemoryAsyncRedis()

    @contextlib.asynccontextmanager
    async def _fake_async_cm(*_args, **_kwargs):
        yield client

    monkeypatch.setattr(auth_router_module, "get_async_redis", _fake_async_cm)
    monkeypatch.setattr(session_checker_module, "get_async_redis", _fake_async_cm)
    monkeypatch.setattr(rate_limiter_module, "get_async_redis", _fake_async_cm)
    monkeypatch.setattr(mfa_module, "get_async_redis", _fake_async_cm)

    return client


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "live: mark test as live integration (requires BRAND_CALIBRATION_LIVE=1)"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("BRAND_CALIBRATION_LIVE", "").strip() in {"1", "true", "yes"}:
        return
    skip_live = pytest.mark.skip(
        reason="Live calibration tests skipped (set BRAND_CALIBRATION_LIVE=1 to run)"
    )
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
