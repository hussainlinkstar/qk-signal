import logging
import json
from typing import Callable, Awaitable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from admin import _get_redis
from database import SessionLocal
from models import OperationalSetting
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MAINTENANCE_CACHE_KEY = "system:maintenance:state"
MAINTENANCE_CACHE_TTL = 10  # 10 seconds

_FAIL_OPEN_STATE: dict = {"active": False, "message": "", "allowed_ips": []}


def _get_maintenance_state() -> dict:
    """Fetch maintenance state with 10s Redis caching.

    Fail-open: if both Redis and DB are unreachable, maintenance is
    treated as inactive so that normal requests are not blocked.
    """
    redis_client = _get_redis()
    if redis_client:
        try:
            cached = redis_client.get(MAINTENANCE_CACHE_KEY)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning("Failed to read maintenance state from Redis: %s", e)

    # Fallback/Refresh from DB
    try:
        db = SessionLocal()
    except Exception:
        logger.warning("Failed to open DB session for maintenance check; failing open.")
        return _FAIL_OPEN_STATE

    try:
        setting = db.query(OperationalSetting).first()
        if not setting:
            state = {
                "active": False,
                "message": "The system is currently undergoing maintenance.",
                "allowed_ips": [],
            }
        else:
            now = datetime.now(timezone.utc)
            is_active = setting.maintenance_mode
            if setting.maintenance_scheduled_start and setting.maintenance_scheduled_end:
                if setting.maintenance_scheduled_start <= now <= setting.maintenance_scheduled_end:
                    is_active = True

            state = {
                "active": is_active,
                "message": setting.maintenance_message
                or "The system is currently undergoing maintenance.",
                "allowed_ips": setting.maintenance_allowed_ips or [],
            }

        # Cache it
        if redis_client:
            try:
                redis_client.setex(MAINTENANCE_CACHE_KEY, MAINTENANCE_CACHE_TTL, json.dumps(state))
            except Exception as e:
                logger.warning("Failed to cache maintenance state to Redis: %s", e)

        return state
    except Exception:
        logger.warning("Failed to query maintenance state from DB; failing open.", exc_info=True)
        return _FAIL_OPEN_STATE
    finally:
        db.close()


class MaintenanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path

        # Bypass rules
        if (
            path.startswith("/api/v1/admin/")
            or path.startswith("/api/system-status/")
            or path.startswith("/api/v1/metrics")
            or path.startswith("/api/v1/auth/login")
        ):
            return await call_next(request)

        # Check maintenance state
        state = _get_maintenance_state()
        if not state["active"]:
            return await call_next(request)

        # IP Allowlist check
        client_ip = request.client.host if request.client else None
        if client_ip and client_ip in state["allowed_ips"]:
            return await call_next(request)

        return JSONResponse(
            status_code=503,
            content={"error": "Maintenance Mode", "message": state["message"], "retry_after": 300},
            headers={"Retry-After": "300"},
        )
