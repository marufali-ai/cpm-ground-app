"""System administration: users, configuration, audit access (PRD 7.7, 72, 89, 99, 116)."""
import csv
import io

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError
from ..ids import token
from ..models import AppConfig, AuditEvent, User
from ..security import ROLE_PERMISSIONS, current_user, hash_password, require
from ..serialize import iso

router = APIRouter(prefix="/admin", tags=["admin"])


class UserCreate(BaseModel):
    name: str
    role: str = "Technician"
    mobile_number: str | None = None
    email: str | None = None
    vendor_code: str | None = None
    password: str | None = None
    vendor_id: str | None = None


class UserPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    status: str | None = None
    email: str | None = None
    password: str | None = None


class ConfigPut(BaseModel):
    value: dict | list | str | int | float | bool | None


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require("*"))):
    return [
        {"user_id": u.user_id, "name": u.name, "role": u.role, "status": u.status,
         "mobile_number": u.mobile_number, "email": u.email, "vendor_code": u.vendor_code,
         "last_login_at": iso(u.last_login_at)}
        for u in db.query(User).order_by(User.created_at).all()
    ]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), _: User = Depends(require("*"))):
    if body.role not in ROLE_PERMISSIONS:
        raise ApiError(422, "ROLE_INVALID", f"Role must be one of {sorted(ROLE_PERMISSIONS)}.")
    if not body.mobile_number and not body.email and not body.vendor_code:
        raise ApiError(400, "IDENTIFIER_REQUIRED", "Provide a mobile number, an email, or a vendor code.")
    uid = token("USR") if body.role != "Technician" else f"TCH-{token('')[-6:]}"
    u = User(
        user_id=uid, name=body.name, role=body.role, mobile_number=body.mobile_number,
        email=body.email, vendor_code=body.vendor_code, vendor_id=body.vendor_id,
        password_hash=hash_password(body.password) if body.password else None,
    )
    db.add(u)
    db.commit()
    return {"user_id": u.user_id, "name": u.name, "role": u.role}


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: UserPatch, db: Session = Depends(get_db), _: User = Depends(require("*"))):
    u = db.get(User, user_id)
    if not u:
        raise ApiError(404, "USER_NOT_FOUND", f"No user {user_id}.")
    if body.role and body.role not in ROLE_PERMISSIONS:
        raise ApiError(422, "ROLE_INVALID", "Unknown role.")
    for f in ("name", "role", "status", "email"):
        v = getattr(body, f)
        if v is not None:
            setattr(u, f, v)
    if body.password:
        u.password_hash = hash_password(body.password)
    db.commit()
    return {"user_id": u.user_id, "name": u.name, "role": u.role, "status": u.status}


@router.get("/config")
def get_config(db: Session = Depends(get_db), _: User = Depends(require("*"))):
    return {row.key: row.value for row in db.query(AppConfig).all()}


@router.put("/config/{key}")
def put_config(key: str, body: ConfigPut, db: Session = Depends(get_db), _: User = Depends(require("*"))):
    row = db.get(AppConfig, key)
    if row is None:
        row = AppConfig(key=key, value=body.value)
        db.add(row)
    else:
        row.value = body.value
    db.commit()
    return {"key": key, "value": row.value}


@router.get("/audit")
def read_audit(
    db: Session = Depends(get_db),
    _: User = Depends(require("audit:view")),
    entity_type: str | None = None,
    entity_id: str | None = None,
    installation_id: str | None = None,
    action: str | None = None,
    performed_by: str | None = None,
    limit: int = Query(default=200, le=2000),
    export: str | None = Query(default=None, description="'csv' for a downloadable export"),
):
    q = db.query(AuditEvent)
    if entity_type:
        q = q.filter(AuditEvent.entity_type == entity_type)
    if entity_id:
        q = q.filter(AuditEvent.entity_id == entity_id)
    if installation_id:
        q = q.filter(AuditEvent.installation_id == installation_id)
    if action:
        q = q.filter(AuditEvent.action == action)
    if performed_by:
        q = q.filter(AuditEvent.performed_by == performed_by)
    rows = q.order_by(AuditEvent.timestamp.desc()).limit(limit).all()
    data = [
        {"audit_id": r.audit_id, "timestamp": iso(r.timestamp), "entity_type": r.entity_type,
         "entity_id": r.entity_id, "installation_id": r.installation_id, "action": r.action,
         "performed_by": r.performed_by, "old_value": r.old_value, "new_value": r.new_value,
         "reason": r.reason, "device_id": r.device_id, "ip_address": r.ip_address}
        for r in rows
    ]
    if export == "csv":
        from fastapi.responses import Response
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(data[0].keys()) if data else ["audit_id"])
        w.writeheader()
        w.writerows(data)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=audit.csv"})
    return data


@router.get("/rbac")
def rbac_matrix(_: User = Depends(current_user)):
    return {r: sorted(p) for r, p in ROLE_PERMISSIONS.items()}
