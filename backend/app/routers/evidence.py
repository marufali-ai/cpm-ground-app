"""Evidence capture, retrieval, replacement, deletion (PRD 36-41, 63, 68, 74, 103).

- Binary is stored in object storage; PostgreSQL holds metadata + hash + reference.
- Uploads are idempotent (Idempotency-Key header or client_uuid) — a retry never duplicates.
- Replacement is non-destructive: prior versions are retained (PRD 41).
- Deletion is allowed only before submission and always writes an audit event (PRD 40).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..audit import record
from ..compliance import compute
from ..config import settings
from ..database import get_db
from ..deps import get_installation
from ..errors import ApiError
from ..ids import token
from ..models import Evidence, EvidenceVersion, Installation, User
from ..security import current_user, require, sha256_hex
from ..serialize import evidence_dict
from ..storage import storage

router = APIRouter(tags=["evidence"])

EVIDENCE_TYPES = {"CCTV", "Monitor", "UPS", "Router", "Selfie", "Issue"}
_MIME = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def _parse_dt(v: str | None):
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def _owner_or_403(user: User, inst: Installation):
    if inst.technician_id != user.user_id and user.role != "SystemAdministrator":
        raise ApiError(403, "FORBIDDEN", "Only the technician who owns this installation can add evidence to it.")


@router.get("/evidence/file")
def download_file(ref: str = Query(...), exp: int = Query(...), sig: str = Query(...)):
    """Serve bytes for a short-lived signed URL. No bearer token — the signature is the capability."""
    if not storage.verify_signature(ref, exp, sig):
        raise ApiError(403, "SIGNED_URL_INVALID", "This evidence link has expired or is invalid.")
    if not storage.exists(ref):
        raise ApiError(404, "FILE_NOT_FOUND", "The stored file is missing.")
    ext = ref.rsplit(".", 1)[-1].lower()
    return Response(storage.read(ref), media_type=_MIME.get(ext, "application/octet-stream"))


@router.post("/evidence/upload", status_code=201)
async def upload_evidence(
    db: Session = Depends(get_db),
    user: User = Depends(require("evidence:create")),
    file: UploadFile = File(...),
    installation_id: str = Form(...),
    evidence_type: str = Form(...),
    equipment_id: str | None = Form(default=None),
    unit_number: str | None = Form(default=None),
    location: str | None = Form(default=None),
    captured_at: str | None = Form(default=None),
    latitude: float | None = Form(default=None),
    longitude: float | None = Form(default=None),
    gps_accuracy: float | None = Form(default=None),
    gps_verified: bool = Form(default=False),
    gps_status: str | None = Form(default=None),
    client_uuid: str | None = Form(default=None),
    watermarked: UploadFile | None = File(default=None),
    batch_id: str | None = Form(default=None),
    idem: str | None = Header(default=None, alias="Idempotency-Key"),
):
    inst = db.get(Installation, installation_id)
    if not inst:
        raise ApiError(404, "INSTALLATION_NOT_FOUND", f"No installation {installation_id}.")
    _owner_or_403(user, inst)
    if evidence_type not in EVIDENCE_TYPES:
        raise ApiError(422, "EVIDENCE_TYPE_INVALID", f"evidence_type must be one of {sorted(EVIDENCE_TYPES)}.")

    # --- idempotent replay (PRD 64) ---
    key = idem or client_uuid
    if key:
        prior = db.query(Evidence).filter(
            (Evidence.idempotency_key == key) | (Evidence.client_uuid == key)
        ).first()
        if prior:
            body = evidence_dict(prior)
            body["replayed"] = True
            return body

    original = await file.read()
    if len(original) == 0:
        raise ApiError(400, "EMPTY_FILE", "The uploaded file is empty.")
    if len(original) > settings.max_upload_mb * 1024 * 1024:
        raise ApiError(413, "PAYLOAD_TOO_LARGE",
                       f"Evidence image exceeds the {settings.max_upload_mb} MB limit.")
    digest = sha256_hex(original)
    dup = db.query(Evidence).filter(Evidence.file_hash == digest, Evidence.status == "active").first()

    ext = (file.filename or "capture.jpg").rsplit(".", 1)[-1].lower()
    if ext not in _MIME:
        ext = "jpg"
    eid = token("EVD")
    orig_ref = storage.save(f"{installation_id}/{eid}/original.{ext}", original)
    wm_ref = None
    if watermarked is not None:
        wm_bytes = await watermarked.read()
        if wm_bytes:
            wm_ref = storage.save(f"{installation_id}/{eid}/watermarked.{ext}", wm_bytes)

    ev = Evidence(
        evidence_id=eid, installation_id=installation_id, equipment_id=equipment_id,
        evidence_type=evidence_type, unit_number=unit_number, location=location,
        file_reference=orig_ref, watermarked_reference=wm_ref, file_hash=digest,
        file_size=len(original), mime_type=_MIME[ext], duplicate_hash=dup is not None,
        captured_at=_parse_dt(captured_at) or datetime.now(timezone.utc),
        uploaded_at=datetime.now(timezone.utc),
        latitude=latitude, longitude=longitude, gps_accuracy=gps_accuracy,
        gps_verified=gps_verified, gps_status=gps_status, technician_id=user.user_id,
        status="active", version=1, client_uuid=client_uuid, idempotency_key=idem,
    )
    db.add(ev)
    if inst.status == "Not Started":
        inst.status = "In Progress"
    record(db, entity_type="evidence", entity_id=eid,
           action="SYNCED" if inst.submitted_at else "CREATED",
           performed_by=user.user_id, installation_id=installation_id,
           new_value=f"{evidence_type} {unit_number or ''}".strip(),
           extra={"hash": digest, "duplicate_hash": dup is not None, "batch_id": batch_id})
    inst.evidence_compliance = compute(db, inst)["percent"]
    db.commit()
    return evidence_dict(ev)


@router.get("/evidence/{evidence_id}")
def get_evidence(
    evidence_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    ev = db.get(Evidence, evidence_id)
    if not ev:
        raise ApiError(404, "EVIDENCE_NOT_FOUND", f"No evidence {evidence_id}.")
    inst = db.get(Installation, ev.installation_id)
    from ..deps import assert_can_view
    assert_can_view(user, inst)
    body = evidence_dict(ev)
    body["versions"] = [
        {"version": v.version, "file_hash": v.file_hash, "reason": v.reason,
         "created_at": v.created_at.isoformat() if v.created_at else None}
        for v in sorted(ev.versions, key=lambda x: x.version)
    ]
    return body


@router.post("/evidence/{evidence_id}/replace")
async def replace_evidence(
    evidence_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require("evidence:replace")),
    file: UploadFile = File(...),
    reason: str = Form(...),
    watermarked: UploadFile | None = File(default=None),
):
    ev = db.get(Evidence, evidence_id)
    if not ev or ev.status == "deleted":
        raise ApiError(404, "EVIDENCE_NOT_FOUND", "That evidence does not exist or was deleted.")
    inst = db.get(Installation, ev.installation_id)
    _owner_or_403(user, inst)
    if not reason.strip():
        raise ApiError(400, "REASON_REQUIRED", "A reason for replacement is required (PRD 41).")

    # keep the current version, non-destructively (PRD 41)
    db.add(EvidenceVersion(
        id=token("EVV"), evidence_id=ev.evidence_id, version=ev.version,
        file_reference=ev.file_reference, watermarked_reference=ev.watermarked_reference,
        file_hash=ev.file_hash, reason=reason.strip(),
    ))
    new_bytes = await file.read()
    if not new_bytes:
        raise ApiError(400, "EMPTY_FILE", "The replacement file is empty.")
    ext = (file.filename or "capture.jpg").rsplit(".", 1)[-1].lower()
    ext = ext if ext in _MIME else "jpg"
    old_hash = ev.file_hash
    ev.version += 1
    ev.file_reference = storage.save(f"{ev.installation_id}/{ev.evidence_id}/v{ev.version}.{ext}", new_bytes)
    ev.file_hash = sha256_hex(new_bytes)
    ev.file_size = len(new_bytes)
    ev.mime_type = _MIME[ext]
    if watermarked is not None:
        wm = await watermarked.read()
        if wm:
            ev.watermarked_reference = storage.save(
                f"{ev.installation_id}/{ev.evidence_id}/v{ev.version}-wm.{ext}", wm)
    ev.uploaded_at = datetime.now(timezone.utc)
    record(db, entity_type="evidence", entity_id=ev.evidence_id, action="REPLACED",
           performed_by=user.user_id, installation_id=ev.installation_id, reason=reason.strip(),
           old_value=f"v{ev.version - 1} {old_hash[:12]}", new_value=f"v{ev.version} {ev.file_hash[:12]}")
    db.commit()
    return evidence_dict(ev)


@router.delete("/evidence/{evidence_id}")
def delete_evidence(
    evidence_id: str,
    reason: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user: User = Depends(require("evidence:delete")),
):
    ev = db.get(Evidence, evidence_id)
    if not ev:
        raise ApiError(404, "EVIDENCE_NOT_FOUND", f"No evidence {evidence_id}.")
    inst = db.get(Installation, ev.installation_id)
    _owner_or_403(user, inst)
    if inst.submitted_at is not None:
        raise ApiError(409, "EVIDENCE_IMMUTABLE_AFTER_SUBMIT",
                       "Submitted evidence cannot be deleted — use replace, which keeps the history.")
    if ev.status == "deleted":
        return {"evidence_id": evidence_id, "status": "deleted"}
    for ref in (ev.file_reference, ev.watermarked_reference):
        if ref:
            storage.delete(ref)
    ev.status = "deleted"
    ev.delete_reason = reason
    ev.file_reference = None
    ev.watermarked_reference = None
    record(db, entity_type="evidence", entity_id=ev.evidence_id, action="DELETED",
           performed_by=user.user_id, installation_id=ev.installation_id, reason=reason,
           old_value=f"{ev.evidence_type} {ev.unit_number or ''}".strip())
    inst.evidence_compliance = compute(db, inst)["percent"]
    db.commit()
    return {"evidence_id": evidence_id, "status": "deleted", "audit": "recorded"}
