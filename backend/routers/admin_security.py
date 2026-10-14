from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

import models
from database import get_db
from auth.token_verifier import get_current_admin_user
from middleware.session_checker import revoke_session_jti

router = APIRouter(prefix="/admin/security", tags=["admin-security"])


@router.get("/events")
def get_security_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    event_type: Optional[str] = None,
    user_id: Optional[int] = None,
    severity: Optional[str] = None,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(get_current_admin_user),
) -> Any:
    """Fetch paginated security events with optional filtering."""
    query = db.query(models.SecurityEvent)

    if event_type:
        query = query.filter(models.SecurityEvent.event_type == event_type)
    if user_id:
        query = query.filter(models.SecurityEvent.user_id == user_id)
    if severity:
        query = query.filter(models.SecurityEvent.severity == severity)

    total = query.count()
    events = query.order_by(desc(models.SecurityEvent.created_at)).offset(skip).limit(limit).all()

    return {
        "total": total,
        "items": [
            {
                "id": ev.id,
                "event_type": ev.event_type,
                "user_id": ev.user_id,
                "ip_address": ev.ip_address,
                "user_agent": ev.user_agent,
                "severity": ev.severity,
                "metadata_json": ev.metadata_json,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            }
            for ev in events
        ],
    }


@router.get("/sessions")
def get_active_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(get_current_admin_user),
) -> Any:
    """List currently active sessions."""
    query = db.query(models.UserSession).filter(models.UserSession.is_active)

    if user_id:
        query = query.filter(models.UserSession.user_id == user_id)

    total = query.count()
    sessions = query.order_by(desc(models.UserSession.created_at)).offset(skip).limit(limit).all()

    return {
        "total": total,
        "items": [
            {
                "id": s.id,
                "user_id": s.user_id,
                "token_jti": s.token_jti,
                "ip_address": s.ip_address,
                "user_agent": s.user_agent,
                "device_name": s.device_name,
                "is_active": s.is_active,
                "last_activity_at": s.last_activity_at.isoformat() if s.last_activity_at else None,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in sessions
        ],
    }


@router.post("/sessions/{session_id}/revoke")
async def revoke_session(
    session_id: int,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(get_current_admin_user),
) -> Any:
    """Revoke a specific session."""
    session = db.query(models.UserSession).filter(models.UserSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if not session.is_active:
        return {"message": "Session is already inactive"}

    session.is_active = False
    db.commit()

    if session.token_jti:
        await revoke_session_jti(session.token_jti)

    # Log the revocation
    from auth.security_events import log_security_event

    log_security_event(
        db,
        event_type="session_revoked_by_admin",
        user_id=session.user_id,
        severity="warning",
        metadata={"admin_id": admin_user.id, "session_id_revoked": session.id},
    )

    return {"message": "Session revoked successfully"}


@router.post("/users/{user_id}/logout-all")
async def logout_all_sessions(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(get_current_admin_user),
) -> Any:
    """Revoke all active sessions for a specific user."""
    active_sessions = (
        db.query(models.UserSession)
        .filter(models.UserSession.user_id == user_id, models.UserSession.is_active)
        .all()
    )

    for session in active_sessions:
        session.is_active = False
        if session.token_jti:
            await revoke_session_jti(session.token_jti)

    db.commit()

    # Log the force logout
    from auth.security_events import log_security_event

    log_security_event(
        db,
        event_type="force_logout_all_by_admin",
        user_id=user_id,
        severity="warning",
        metadata={"admin_id": admin_user.id, "sessions_revoked_count": len(active_sessions)},
    )

    return {
        "message": f"Successfully revoked {len(active_sessions)} active sessions for user {user_id}"
    }
