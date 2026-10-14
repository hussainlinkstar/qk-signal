from __future__ import annotations

import hmac
import logging
import os
import time
from enum import Enum

import pyotp

from core.redis_client import get_async_redis

logger = logging.getLogger(__name__)

MFA_ISSUER = os.getenv("MFA_ISSUER", "Qiko Signal")

TOTP_INTERVAL_SECONDS = 30
TOTP_VALID_WINDOW = 1

# SIGV2-1244: a code minted for timestep S is accepted while the clock sits
# anywhere in [S - TOTP_VALID_WINDOW, S + TOTP_VALID_WINDOW], so the "already
# used" marker has to outlive 2 * TOTP_VALID_WINDOW + 1 timesteps, plus a
# margin for clock skew between the API nodes.
USED_TIMESTEP_TTL_SECONDS = (2 * TOTP_VALID_WINDOW + 1) * TOTP_INTERVAL_SECONDS + 30

USED_TIMESTEP_KEY_PREFIX = "mfa:totp:used:"
FAILED_ATTEMPT_KEY_PREFIX = "mfa:attempts:"
MAX_FAILED_ATTEMPTS = 10
FAILED_ATTEMPT_WINDOW_SECONDS = 15 * 60


class MFAVerificationResult(str, Enum):
    """Outcome of a per-user TOTP verification."""

    OK = "ok"
    INVALID = "invalid"
    REPLAYED = "replayed"
    THROTTLED = "throttled"
    UNAVAILABLE = "unavailable"


def normalize_otp_code(value: str | None) -> str | None:
    if not value:
        return None

    normalized = "".join(character for character in value if character.isdigit())
    if len(normalized) != 6:
        return None

    return normalized


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def build_totp_uri(secret: str, account_name: str, issuer: str = MFA_ISSUER) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=issuer)


def matching_totp_timestep(
    secret: str, otp_code: str | None, *, for_time: float | None = None
) -> int | None:
    """Return the TOTP timestep *otp_code* is valid for, or ``None``.

    Same acceptance window as ``pyotp.TOTP.verify(..., valid_window=1)``, but it
    reports *which* timestep matched so the caller can burn that timestep and
    refuse a replay.
    """
    normalized = normalize_otp_code(otp_code)
    if not normalized:
        return None

    totp = pyotp.TOTP(secret, interval=TOTP_INTERVAL_SECONDS)
    now = time.time() if for_time is None else for_time
    current_step = int(now // TOTP_INTERVAL_SECONDS)

    for offset in range(-TOTP_VALID_WINDOW, TOTP_VALID_WINDOW + 1):
        candidate_step = current_step + offset
        if hmac.compare_digest(totp.generate_otp(candidate_step), normalized):
            return candidate_step

    return None


# SIGV2-1258: the unprotected ``verify_totp_code`` helper is gone. Every caller
# must go through ``verify_totp_code_for_user`` below, which burns the timestep
# and counts failures; keeping a stateless variant around is how the MFA
# management endpoints ended up without replay protection in the first place.


async def mfa_throttle_retry_after(user_id: int | str) -> int | None:
    """Seconds the user must wait, or ``None`` when they are not locked out.

    Throttling is deliberately fail-open: a Redis outage must not lock every
    account out of login. The replay guard below is the fail-closed control.
    """
    key = f"{FAILED_ATTEMPT_KEY_PREFIX}{user_id}"
    try:
        async with get_async_redis() as client:
            raw = await client.get(key)
            if raw is None:
                return None
            attempts = int(raw)
            if attempts < MAX_FAILED_ATTEMPTS:
                return None
            ttl = await client.ttl(key)
    except Exception:
        # Includes a corrupt counter value; either way the user is let through.
        logger.warning(
            "MFA throttle lookup failed; allowing the attempt (fail-open). code=mfa_throttle_unavailable"
        )
        return None

    try:
        remaining = int(ttl)
    except (TypeError, ValueError):
        remaining = FAILED_ATTEMPT_WINDOW_SECONDS

    if remaining <= 0:
        remaining = FAILED_ATTEMPT_WINDOW_SECONDS

    return remaining


async def record_mfa_failure(user_id: int | str) -> None:
    key = f"{FAILED_ATTEMPT_KEY_PREFIX}{user_id}"
    try:
        async with get_async_redis() as client:
            attempts = await client.incr(key)
            if int(attempts) <= 1:
                await client.expire(key, FAILED_ATTEMPT_WINDOW_SECONDS)
    except Exception:
        logger.warning(
            "MFA failure counter update failed. code=mfa_throttle_write_failed",
        )


async def clear_mfa_failures(user_id: int | str) -> None:
    try:
        async with get_async_redis() as client:
            await client.delete(f"{FAILED_ATTEMPT_KEY_PREFIX}{user_id}")
    except Exception:
        logger.warning(
            "MFA failure counter reset failed. code=mfa_throttle_reset_failed",
        )


async def claim_totp_timestep(user_id: int | str, timestep: int) -> bool | None:
    """Burn *timestep* for *user_id*.

    Returns ``True`` when this call claimed the timestep, ``False`` when it was
    already consumed (a replay), and ``None`` when Redis could not answer. The
    caller must treat ``None`` as a rejection: the replay guard is fail-closed.
    """
    key = f"{USED_TIMESTEP_KEY_PREFIX}{user_id}:{timestep}"
    try:
        async with get_async_redis() as client:
            claimed = await client.set(key, "1", nx=True, ex=USED_TIMESTEP_TTL_SECONDS)
    except Exception:
        logger.warning(
            "MFA replay guard unavailable; rejecting the attempt (fail-closed). code=mfa_replay_guard_unavailable"
        )
        return None
    return bool(claimed)


async def verify_totp_code_for_user(
    *, user_id: int | str, secret: str, otp_code: str | None
) -> MFAVerificationResult:
    """Verify a TOTP code once, with per-user replay protection and throttling."""
    if await mfa_throttle_retry_after(user_id) is not None:
        return MFAVerificationResult.THROTTLED

    timestep = matching_totp_timestep(secret, otp_code)
    if timestep is None:
        await record_mfa_failure(user_id)
        return MFAVerificationResult.INVALID

    claimed = await claim_totp_timestep(user_id, timestep)
    if claimed is None:
        return MFAVerificationResult.UNAVAILABLE
    if not claimed:
        await record_mfa_failure(user_id)
        return MFAVerificationResult.REPLAYED

    await clear_mfa_failures(user_id)
    return MFAVerificationResult.OK
