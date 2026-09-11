"""ORM -> plain dict for API responses. Evidence gets a fresh signed URL each read (PRD 74)."""
from .models import Equipment, Evidence, Installation, Issue
from .storage import storage


def iso(dt):
    return dt.isoformat() if dt else None


def equipment_dict(q: Equipment) -> dict:
    return {
        "equipment_id": q.equipment_id,
        "equipment_type": q.equipment_type,
        "unit_number": q.unit_number,
        "location": q.location,
        "custom_location": q.custom_location,
        "serial_number": q.serial_number,
        "status": q.status,
        "remarks": q.remarks,
        "internet_working": q.internet_working,
        "speed_test": q.speed_test,
        "created_at": iso(q.created_at),
        "updated_at": iso(q.updated_at),
    }


def evidence_dict(e: Evidence, *, with_url: bool = True) -> dict:
    ref = e.watermarked_reference or e.file_reference
    return {
        "evidence_id": e.evidence_id,
        "installation_id": e.installation_id,
        "equipment_id": e.equipment_id,
        "evidence_type": e.evidence_type,
        "unit_number": e.unit_number,
        "location": e.location,
        "file_hash": e.file_hash,
        "file_size": e.file_size,
        "mime_type": e.mime_type,
        "duplicate_hash": e.duplicate_hash,
        "captured_at": iso(e.captured_at),
        "uploaded_at": iso(e.uploaded_at),
        "latitude": e.latitude,
        "longitude": e.longitude,
        "gps_accuracy": e.gps_accuracy,
        "gps_verified": e.gps_verified,
        "gps_status": e.gps_status,
        "technician_id": e.technician_id,
        "status": e.status,
        "version": e.version,
        "delete_reason": e.delete_reason,
        "signed_url": storage.signed_url(ref) if (with_url and ref) else None,
        "created_at": iso(e.created_at),
    }


def issue_dict(i: Issue) -> dict:
    return {
        "issue_id": i.issue_id,
        "installation_id": i.installation_id,
        "equipment_id": i.equipment_id,
        "scope": i.scope,
        "severity": i.severity,
        "category": i.category,
        "description": i.description,
        "evidence_id": i.evidence_id,
        "status": i.status,
        "created_by": i.created_by,
        "created_at": iso(i.created_at),
        "updated_at": iso(i.updated_at),
    }


def installation_dict(inst: Installation, *, full: bool = False) -> dict:
    base = {
        "installation_id": inst.installation_id,
        "project_id": inst.project_id,
        "center_id": inst.center_id,
        "technician_id": inst.technician_id,
        "status": inst.status,
        "evidence_compliance": inst.evidence_compliance,
        "gps": {
            "status": inst.gps_status,
            "latitude": inst.gps_latitude,
            "longitude": inst.gps_longitude,
            "accuracy": inst.gps_accuracy,
            "distance_m": inst.gps_distance_m,
        },
        "started_at": iso(inst.started_at),
        "submitted_at": iso(inst.submitted_at),
        "created_at": iso(inst.created_at),
        "updated_at": iso(inst.updated_at),
        "submitted": inst.submitted_at is not None,
    }
    if full:
        base["equipment"] = [equipment_dict(q) for q in inst.equipment]
        base["evidence"] = [evidence_dict(e) for e in inst.evidence if e.status != "deleted"]
        base["issues"] = [issue_dict(i) for i in inst.issues]
        base["submissions"] = [
            {
                "submission_id": s.submission_id,
                "status_at_submission": s.status_at_submission,
                "compliance_at_submission": s.compliance_at_submission,
                "acknowledged": s.acknowledged,
                "created_by": s.created_by,
                "created_at": iso(s.created_at),
            }
            for s in inst.submissions
        ]
    return base
