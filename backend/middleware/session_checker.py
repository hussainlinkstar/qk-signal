from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import jwt
import logging
from core.config import settings
from core.redis_client import get_async_redis

logger = logging.getLogger(__name__)

JWT_SECRET_KEY = settings.JWT_SECRET_KEY
_SESSION_REVOCATION_PREFIX = "session:revoked:"


async def revoke_session_jti(jti: str, ttl_days: int = 30) -> bool:
    """Add a session JTI to the Redis deny list. Returns True when it was written."""
    try:
        async with get_async_redis() as client:
            ttl_seconds = ttl_days * 86400
            await client.setex(f"{_SESSION_REVOCATION_PREFIX}{jti}", ttl_seconds, "1")
        return True
    except Exception as e:
        logger.error(f"Failed to revoke session in Redis: {e}")
        return False


async def revoke_session_jtis(session_jtis: list[str]) -> int:
    """Deny-list every session JTI. Best-effort per JTI; returns the count revoked."""
    revoked = 0
    for jti in session_jtis:
        if await revoke_session_jti(jti):
            revoked += 1
    return revoked


def deactivate_user_sessions(db, user_id) -> list[str]:
    """Mark every UserSession row of the user inactive and return their JTIs.

    Deactivation rejects outstanding refresh tokens at /auth/refresh; the
    returned JTIs must still be passed to revoke_session_jtis so in-flight
    access tokens fail the revocation middleware immediately.
    """
    import models

    sessions = db.query(models.UserSession).filter(models.UserSession.user_id == user_id).all()
    session_jtis = [s.token_jti for s in sessions if s.token_jti]
    for session in sessions:
        session.is_active = False
    db.commit()
    return session_jtis


class SessionRevocationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header[7:]
            try:
                # Fast parse without signature verification to extract JTI.
                unverified_claims = jwt.decode(token, options={"verify_signature": False})
            except Exception:
                # Token validity will be thoroughly verified downstream.
                unverified_claims = None
            jti = unverified_claims.get("jti") if unverified_claims else None
            if jti:
                try:
                    async with get_async_redis() as client:
                        is_revoked = await client.exists(f"{_SESSION_REVOCATION_PREFIX}{jti}")
                except Exception as exc:
                    # Fail closed: the whole point of the deny list is to stop
                    # a known-bad credential, so a Redis outage rejects the
                    # request instead of letting a revoked session through.
                    logger.error(
                        "SESSION_REVOCATION_UNAVAILABLE: cannot verify session revocation: %s",
                        exc,
                    )
                    return JSONResponse(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        content={
                            "detail": "Cannot verify session revocation. Please try again later."
                        },
                    )
                if is_revoked:
                    return JSONResponse(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        content={"detail": "Session has been revoked"},
                    )

        response = await call_next(request)
        return response
