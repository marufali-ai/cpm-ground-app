"""Append-only audit writer (PRD 71, 99, 113 'Audit by Design').

There is deliberately no update or delete path for AuditEvent rows.
"""
from sqlalchemy.orm import Session

from .ids import token
from .models import AuditEvent


def record(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    performed_by: str | None = None,
    installation_id: str | None = None,
    old_value=None,
    new_value=None,
    reason: str | None = None,
    device_id: str | None = None,
    ip_address: str | None = None,
    extra: dict | None = None,
) -> AuditEvent:
    ev = AuditEvent(
        audit_id=token("AUD"),
        entity_type=entity_type,
        entity_id=entity_id,
        installation_id=installation_id,
        action=action,
        performed_by=performed_by,
        old_value=None if old_value is None else str(old_value),
        new_value=None if new_value is None else str(new_value),
        reason=reason,
        device_id=device_id,
        ip_address=ip_address,
        extra=extra or {},
    )
    db.add(ev)
    return ev
