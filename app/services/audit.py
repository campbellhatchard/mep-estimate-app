from typing import Any
from sqlalchemy.orm import Session
from ..models import AuditEvent

def record(db: Session, *, event_type: str, user_id: int | None, estimate_id: int | None = None,
           revision_id: int | None = None, config_version_id: int | None = None,
           field_name: str | None = None, old_value: Any = None, new_value: Any = None,
           reason: str | None = None, source: str = "WEB"):
    event = AuditEvent(
        estimate_id=estimate_id,
        revision_id=revision_id,
        config_version_id=config_version_id,
        event_type=event_type,
        field_name=field_name,
        old_value=None if old_value is None else str(old_value),
        new_value=None if new_value is None else str(new_value),
        reason=reason,
        user_id=user_id,
        source=source,
    )
    db.add(event)
    return event
