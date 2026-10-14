from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from models import SecurityEvent
import logging

logger = logging.getLogger(__name__)


def log_security_event(
    db: Session,
    event_type: str,
    user_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    severity: str = "info",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log a security event to the database.
    Does not raise exceptions if logging fails to prevent breaking auth flows.
    """
    try:
        event = SecurityEvent(
            event_type=event_type,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            severity=severity,
            metadata_json=metadata,
        )
        db.add(event)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log security event '{event_type}': {e}")
        db.rollback()
