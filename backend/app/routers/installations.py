"""Installations, equipment, timeline, compliance (PRD 17-21, 33, 63, 67, 69, 91)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..audit import record
from ..compliance import compute
from ..database import get_db
from ..deps import assert_can_view, assert_owner_technician, get_installation, remember, replay
from ..errors import ApiError
from ..ids import installation_id as new_installation_id
from ..ids import token
from ..models import (
    AssetRegistry,
    AuditEvent,
    Center,
    Equipment,
    Installation,
    Project,
    Submission,
    User,
)
from ..schemas import EquipmentCreate, EquipmentPatch, InstallationCreate, InstallationPatch, SubmitRequest
from ..security import current_user, has_permission, require
from ..serialize import equipment_dict, installation_dict, iso

router = APIRouter(tags=["installations"])

VALID_STATUS = {"Not Started", "In Progress", "Partially Completed", "Completed"}
EQUIP_TYPES = {"CCTV", "Monitor", "UPS", "Router", "Other"}


def _refresh_compliance(db: Session, inst: Installation) -> float:
    inst.evidence_compliance = compute(db, inst)["percent"]
    return inst.evidence_compliance


@router.post("/installations", status_code=201)
def create_installation(
    body: InstallationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require("installation:create")),
    idem: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if body.client_uuid:
        existing = db.query(Installation).filter(Installation.client_uuid == body.client_uuid).first()
        if existing:
            return installation_dict(existing, full=True)
    seen = replay(db, idem, "POST /installations")
    if seen:
        return seen[1]

    project = db.get(Project, body.project_id)
    center = db.get(Center, body.center_id)
    if not project or not center:
        raise ApiError(404, "MASTER_NOT_FOUND", "Project or center does not exist.")
    if center.project_id != project.project_id:
        raise ApiError(400, "CENTER_PROJECT_MISMATCH", "That center is not in that project.")

    g = body.gps
    inst = Installation(
        installation_id=new_installation_id(db),
        project_id=project.project_id, center_id=center.center_id, technician_id=user.user_id,
        client_uuid=body.client_uuid, status="Not Started",
        gps_status=g.status if g else None,
        gps_latitude=g.latitude if g else None, gps_longitude=g.longitude if g else None,
        gps_accuracy=g.accuracy if g else None, gps_distance_m=g.distance_m if g else None,
    )
    db.add(inst)
    db.flush()
    record(db, entity_type="installation", entity_id=inst.installation_id, action="CREATED",
           performed_by=user.user_id, installation_id=inst.installation_id,
           new_value=center.center_code, device_id=body.device_id)
    body_out = installation_dict(inst, full=True)
    remember(db, idem, "POST /installations", user.user_id, 201, body_out)
    db.commit()
    return body_out


@router.get("/installations")
def list_installations(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    status: str | None = Query(default=None),
    center_id: str | None = Query(default=None),
    mine: bool = Query(default=False),
    submitted: bool | None = Query(default=None),
):
    q = db.query(Installation)
    if not has_permission(user.role, "installation:view:all"):
        if has_permission(user.role, "installation:view:vendor"):
            q = q.filter(or_(Installation.technician_id == user.user_id,
                             Installation.submitted_at.isnot(None)))
        else:
            q = q.filter(Installation.technician_id == user.user_id)
    if mine:
        q = q.filter(Installation.technician_id == user.user_id)
    if status:
        q = q.filter(Installation.status == status)
    if center_id:
        q = q.filter(Installation.center_id == center_id)
    if submitted is True:
        q = q.filter(Installation.submitted_at.isnot(None))
    if submitted is False:
        q = q.filter(Installation.submitted_at.is_(None))
    rows = q.order_by(Installation.created_at.desc()).limit(500).all()
    return [installation_dict(i) for i in rows]


@router.get("/installations/{installation_id}")
def get_one(
    inst: Installation = Depends(get_installation),
    user: User = Depends(current_user),
):
    assert_can_view(user, inst)
    return installation_dict(inst, full=True)


@router.patch("/installations/{installation_id}")
def patch_installation(
    body: InstallationPatch,
    inst: Installation = Depends(get_installation),
    db: Session = Depends(get_db),
    user: User = Depends(require("installation:update")),
):
    assert_owner_technician(user, inst)
    if inst.submitted_at is not None and body.status is not None:
        raise ApiError(409, "INSTALLATION_SUBMITTED",
                       "This installation is submitted; its status can no longer be changed from the app.")
    if body.status is not None:
        if body.status not in VALID_STATUS:
            raise ApiError(422, "STATUS_INVALID", f"Status must be one of: {', '.join(sorted(VALID_STATUS))}.")
        old = inst.status
        inst.status = body.status
        record(db, entity_type="installation", entity_id=inst.installation_id, action="STATUS_CHANGED",
               performed_by=user.user_id, installation_id=inst.installation_id,
               old_value=old, new_value=body.status, device_id=body.device_id)
    if body.gps:
        g = body.gps
        inst.gps_status, inst.gps_latitude, inst.gps_longitude = g.status, g.latitude, g.longitude
        inst.gps_accuracy, inst.gps_distance_m = g.accuracy, g.distance_m
    _refresh_compliance(db, inst)
    db.commit()
    return installation_dict(inst, full=True)


@router.post("/installations/{installation_id}/submit")
def submit_installation(
    body: SubmitRequest,
    inst: Installation = Depends(get_installation),
    db: Session = Depends(get_db),
    user: User = Depends(require("installation:submit")),
    idem: str | None = Header(default=None, alias="Idempotency-Key"),
):
    assert_owner_technician(user, inst)
    if body.status not in VALID_STATUS:
        raise ApiError(422, "STATUS_INVALID", "Invalid installation status.")
    if not body.acknowledged:
        raise ApiError(400, "REVIEW_NOT_ACKNOWLEDGED", "Confirm you have reviewed the installation before submitting.")

    if body.client_uuid:
        prev = db.query(Submission).filter(Submission.client_uuid == body.client_uuid).first()
        if prev:
            return {"submission_id": prev.submission_id, "installation_id": inst.installation_id,
                    "status": inst.status, "compliance": prev.compliance_at_submission, "replayed": True}
    seen = replay(db, idem, "POST /installations/submit")
    if seen:
        return seen[1]

    comp = compute(db, inst)
    inst.status = body.status                       # technician's call — recorded verbatim (PRD 19)
    inst.evidence_compliance = comp["percent"]
    inst.submitted_at = datetime.now(timezone.utc)
    sub = Submission(
        submission_id=token("SUB"), installation_id=inst.installation_id, client_uuid=body.client_uuid,
        status_at_submission=body.status, compliance_at_submission=comp["percent"],
        submission_selfie_id=body.submission_selfie_evidence_id, acknowledged=True, created_by=user.user_id,
    )
    db.add(sub)
    record(db, entity_type="submission", entity_id=sub.submission_id, action="SUBMITTED",
           performed_by=user.user_id, installation_id=inst.installation_id,
           new_value=f"{body.status} @ {comp['percent']}%", device_id=body.device_id,
           extra={"cctv_missing": comp["cctv_missing"], "completion_warning":
                  body.status == "Completed" and comp["percent"] < 100})
    out = {"submission_id": sub.submission_id, "installation_id": inst.installation_id,
           "status": inst.status, "compliance": comp["percent"],
           "cctv_missing": comp["cctv_missing"], "submitted_at": iso(inst.submitted_at)}
    remember(db, idem, "POST /installations/submit", user.user_id, 200, out)
    db.commit()
    return out


@router.get("/installations/{installation_id}/timeline")
def timeline(
    inst: Installation = Depends(get_installation),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    assert_can_view(user, inst)
    rows = (
        db.query(AuditEvent)
        .filter(AuditEvent.installation_id == inst.installation_id)
        .order_by(AuditEvent.timestamp.asc())
        .all()
    )
    return [
        {"timestamp": iso(r.timestamp), "action": r.action, "entity_type": r.entity_type,
         "entity_id": r.entity_id, "by": r.performed_by, "detail": r.new_value or r.reason}
        for r in rows
    ]


@router.get("/installations/{installation_id}/compliance")
def compliance(
    inst: Installation = Depends(get_installation),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    assert_can_view(user, inst)
    return compute(db, inst)


# --------------------------------------------------------------------------- #
# Equipment
# --------------------------------------------------------------------------- #
@router.post("/installations/{installation_id}/equipment", status_code=201)
def add_equipment(
    body: EquipmentCreate,
    inst: Installation = Depends(get_installation),
    db: Session = Depends(get_db),
    user: User = Depends(require("installation:update")),
):
    assert_owner_technician(user, inst)
    if inst.submitted_at is not None:
        raise ApiError(409, "INSTALLATION_SUBMITTED", "This installation is submitted and can no longer be edited.")
    if body.equipment_type not in EQUIP_TYPES:
        raise ApiError(422, "EQUIP_TYPE_INVALID", f"Equipment type must be one of: {', '.join(sorted(EQUIP_TYPES))}.")
    dup = (
        db.query(Equipment)
        .filter(Equipment.installation_id == inst.installation_id,
                Equipment.equipment_type == body.equipment_type,
                Equipment.unit_number == body.unit_number)
        .first()
    )
    if dup:
        raise ApiError(409, "UNIT_NUMBER_DUPLICATE",
                       f'"{body.unit_number}" is already used for a {body.equipment_type} in this installation. '
                       "Please enter a different number.")

    serial_conflict = None
    if body.serial_number:
        reg = db.query(AssetRegistry).filter(AssetRegistry.serial_number.ilike(body.serial_number.strip())).first()
        other = (
            db.query(Equipment)
            .filter(Equipment.serial_number.ilike(body.serial_number.strip()),
                    Equipment.installation_id != inst.installation_id)
            .first()
        )
        if reg:
            serial_conflict = {"source": "asset_registry", "center_code": reg.center_code,
                               "equipment_type": reg.equipment_type}
        elif other:
            serial_conflict = {"source": "installation", "installation_id": other.installation_id}

    q = Equipment(
        equipment_id=token("EQP"), installation_id=inst.installation_id,
        equipment_type=body.equipment_type, unit_number=body.unit_number,
        location=body.location, custom_location=body.custom_location,
        serial_number=(body.serial_number or None), status=body.status, remarks=body.remarks,
        internet_working=body.internet_working, speed_test=body.speed_test,
    )
    db.add(q)
    if body.serial_number:
        db.add(AssetRegistry(
            id=token("ASR"), serial_number=body.serial_number.strip(), equipment_type=body.equipment_type,
            center_code=db.get(Center, inst.center_id).center_code, installation_id=inst.installation_id,
        ))
    if inst.status == "Not Started":
        inst.status = "In Progress"
    record(db, entity_type="equipment", entity_id=q.equipment_id, action="CREATED",
           performed_by=user.user_id, installation_id=inst.installation_id,
           new_value=f"{body.equipment_type} {body.unit_number}")
    _refresh_compliance(db, inst)
    db.commit()
    out = equipment_dict(q)
    out["serial_conflict"] = serial_conflict  # advisory (PRD 35) — creation still succeeds
    return out


@router.patch("/equipment/{equipment_id}")
def patch_equipment(
    equipment_id: str,
    body: EquipmentPatch,
    db: Session = Depends(get_db),
    user: User = Depends(require("installation:update")),
):
    q = db.get(Equipment, equipment_id)
    if not q:
        raise ApiError(404, "EQUIPMENT_NOT_FOUND", f"No equipment {equipment_id}.")
    inst = db.get(Installation, q.installation_id)
    assert_owner_technician(user, inst)
    if inst.submitted_at is not None:
        raise ApiError(409, "INSTALLATION_SUBMITTED", "This installation is submitted and can no longer be edited.")

    if body.unit_number and body.unit_number != q.unit_number:
        clash = (
            db.query(Equipment)
            .filter(Equipment.installation_id == q.installation_id,
                    Equipment.equipment_type == q.equipment_type,
                    Equipment.unit_number == body.unit_number,
                    Equipment.equipment_id != q.equipment_id)
            .first()
        )
        if clash:
            raise ApiError(409, "UNIT_NUMBER_DUPLICATE",
                           f'"{body.unit_number}" is already used in this installation.')
        record(db, entity_type="equipment", entity_id=q.equipment_id, action="UPDATED",
               performed_by=user.user_id, installation_id=q.installation_id,
               old_value=q.unit_number, new_value=body.unit_number)
        q.unit_number = body.unit_number

    for field in ("location", "custom_location", "status", "remarks", "speed_test"):
        val = getattr(body, field)
        if val is not None:
            setattr(q, field, val)
    if body.internet_working is not None:
        q.internet_working = body.internet_working
        record(db, entity_type="equipment", entity_id=q.equipment_id, action="UPDATED",
               performed_by=user.user_id, installation_id=q.installation_id,
               new_value=f"internet_working={body.internet_working}")
    if body.serial_number is not None:
        q.serial_number = body.serial_number.strip() or None
        if q.serial_number:
            db.add(AssetRegistry(
                id=token("ASR"), serial_number=q.serial_number, equipment_type=q.equipment_type,
                center_code=db.get(Center, inst.center_id).center_code,
                installation_id=q.installation_id,
            ))
    _refresh_compliance(db, inst)
    db.commit()
    return equipment_dict(q)
