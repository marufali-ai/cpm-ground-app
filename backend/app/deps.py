"""Shared route helpers: fetch-or-404, RBAC visibility, generic idempotency replay (PRD 64)."""
from fastapi import Depends
from sqlalchemy.orm import Session

from .database import get_db
from .errors import ApiError
from .models import IdempotencyKey, Installation, User
from .security import current_user, has_permission


def get_installation(installation_id: str, db: Session = Depends(get_db)) -> Installation:
    inst = db.get(Installation, installation_id)
    if inst is None:
        raise ApiError(404, "INSTALLATION_NOT_FOUND", f"No installation {installation_id}.")
    return inst


def can_view_installation(user: User, inst: Installation) -> bool:
    if has_permission(user.role, "installation:view:all"):
        return True
    if has_permission(user.role, "installation:view:vendor") and inst.submitted_at is not None:
        return True
    return inst.technician_id == user.user_id


def assert_can_view(user: User, inst: Installation) -> None:
    if not can_view_installation(user, inst):
        raise ApiError(403, "FORBIDDEN", "You are not permitted to view this installation.")


def assert_owner_technician(user: User, inst: Installation) -> None:
    if inst.technician_id != user.user_id and not has_permission(user.role, "*"):
        raise ApiError(403, "FORBIDDEN", "Only the technician who created this installation can change it.")


def replay(db: Session, key: str | None, route: str):
    """Return a stored response for a seen Idempotency-Key, else None (PRD 64: retries never duplicate)."""
    if not key:
        return None
    row = db.get(IdempotencyKey, key)
    if row and row.route == route:
        return row.status_code, row.response_json
    return None


def remember(db: Session, key: str | None, route: str, user_id: str | None, status_code: int, body: dict) -> None:
    if not key:
        return
    if db.get(IdempotencyKey, key) is None:
        db.add(IdempotencyKey(key=key, route=route, user_id=user_id, status_code=status_code, response_json=body))


__all__ = [
    "get_db", "current_user", "get_installation", "assert_can_view",
    "assert_owner_technician", "replay", "remember",
]
