"""Share-token decisions for public audit links (SIGV2-1250).

One place owns three concerns that used to be spread across the router, or
missing entirely:

* **Comparison.** The candidate token is compared with ``secrets.compare_digest``
  on the encoded bytes, so neither the length nor a shared prefix is readable
  from the response time, and a non-ASCII candidate cannot raise.
* **Expiry.** A token now carries a deadline (``audits.share_token_expires_at``,
  default 30 days, ``settings.AUDIT_SHARE_TOKEN_TTL_DAYS``). A token minted
  before this change has NULL there, which means "no expiry recorded": it keeps
  working until it is rotated, so no existing share link was invalidated
  retroactively.
* **Rotation.** Minting a new token replaces the old one, which stops matching
  immediately, so an expired link is re-issued rather than resurrected.

Every function mutates only the two columns on the instance it is given and
never touches the session: the caller decides when to commit.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from core.config import settings

__all__ = [
    "is_share_token_expired",
    "issue_share_token",
    "new_share_token",
    "rotate_share_token",
    "share_token_matches",
    "share_token_ttl_days",
]

_DEFAULT_TTL_DAYS = 30


def new_share_token() -> str:
    """Mint a fresh token: 128 bits of randomness, hex encoded."""
    return uuid.uuid4().hex


def share_token_ttl_days(ttl_days: int | None = None) -> int:
    if ttl_days is not None:
        return int(ttl_days)
    configured = getattr(settings, "AUDIT_SHARE_TOKEN_TTL_DAYS", _DEFAULT_TTL_DAYS)
    try:
        resolved = int(configured)
    except (TypeError, ValueError):
        return _DEFAULT_TTL_DAYS
    return resolved if resolved > 0 else _DEFAULT_TTL_DAYS


def _now(now: datetime | None = None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Read a stored timestamp as UTC when the driver returned it naive."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def is_share_token_expired(audit: Any, *, now: datetime | None = None) -> bool:
    """Whether this audit's share token is past its deadline.

    A missing deadline is not an expiry: it marks a token minted before
    expiries were recorded.
    """
    expires_at = getattr(audit, "share_token_expires_at", None)
    if expires_at is None:
        return False
    return _as_utc(expires_at) <= _now(now)


def share_token_matches(audit: Any, candidate: Any, *, now: datetime | None = None) -> bool:
    """Whether *candidate* is this audit's current, unexpired share token."""
    stored = getattr(audit, "share_token", None)
    if not stored or not candidate:
        return False

    stored_bytes = str(stored).encode("utf-8", "surrogatepass")
    candidate_bytes = str(candidate).encode("utf-8", "surrogatepass")
    if not secrets.compare_digest(stored_bytes, candidate_bytes):
        return False

    return not is_share_token_expired(audit, now=now)


def rotate_share_token(
    audit: Any,
    *,
    now: datetime | None = None,
    ttl_days: int | None = None,
) -> str:
    """Replace the share token and its deadline, and return the new token.

    The previous token stops matching as soon as the caller commits.
    """
    audit.share_token = new_share_token()
    audit.share_token_expires_at = _now(now) + timedelta(days=share_token_ttl_days(ttl_days))
    return audit.share_token


def issue_share_token(
    audit: Any,
    *,
    now: datetime | None = None,
    ttl_days: int | None = None,
) -> str:
    """Return a usable share token for *audit*, minting one only if needed.

    An existing token that is still valid is returned untouched, deadline
    included, so asking twice gives the same link. An absent or expired token
    is replaced.
    """
    if getattr(audit, "share_token", None) and not is_share_token_expired(audit, now=now):
        return audit.share_token
    return rotate_share_token(audit, now=now, ttl_days=ttl_days)
