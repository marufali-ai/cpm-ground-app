"""Synchronisation session lifecycle (PRD 49, 50, 63, 104).

session  -> declare how many items a device is about to push
upload   -> (use POST /evidence/upload with the batch_id form field)
acknowledge -> server confirms receipt; returns the authoritative list so the client
               can mark items Synced and prevent duplicate re-sends.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..audit import record
from ..database import get_db
from ..deps import assert_owner_technician
from ..errors import ApiError
from ..ids import token
from ..models import Evidence, Installation, SyncBatch, User
from ..schemas import SyncAckRequest, SyncSessionRequest
from ..security import require

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/session", status_code=201)
def open_session(
    body: SyncSessionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require("sync:write")),
):
    inst = db.get(Installation, body.installation_id)
    if not inst:
        raise ApiError(404, "INSTALLATION_NOT_FOUND", f"No installation {body.installation_id}.")
    assert_owner_technician(user, inst)
    batch = SyncBatch(
        batch_id=token("SYB"), installation_id=inst.installation_id, device_id=body.device_id,
        user_id=user.user_id, declared_items=body.declared_items, status="open",
    )
    db.add(batch)
    db.commit()
    return {"batch_id": batch.batch_id, "installation_id": inst.installation_id,
            "declared_items": batch.declared_items, "status": batch.status}


@router.post("/acknowledge")
def acknowledge(
    body: SyncAckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require("sync:write")),
):
    batch = db.get(SyncBatch, body.batch_id)
    if not batch:
        raise ApiError(404, "BATCH_NOT_FOUND", f"No sync batch {body.batch_id}.")
    inst = db.get(Installation, batch.installation_id)
    assert_owner_technician(user, inst)

    stored = (
        db.query(Evidence)
        .filter(Evidence.installation_id == inst.installation_id, Evidence.status == "active")
        .all()
    )
    batch.received_items = len(stored)
    batch.status = "acknowledged"
    batch.acknowledged_at = datetime.now(timezone.utc)
    record(db, entity_type="installation", entity_id=inst.installation_id, action="SYNCED",
           performed_by=user.user_id, installation_id=inst.installation_id,
           new_value=f"batch {batch.batch_id}: {batch.received_items} items on server",
           device_id=batch.device_id)
    db.commit()
    return {
        "batch_id": batch.batch_id,
        "installation_id": inst.installation_id,
        "declared_items": batch.declared_items,
        "received_items": batch.received_items,
        "server_evidence_ids": [e.evidence_id for e in stored],
        "server_hashes": [e.file_hash for e in stored],
        "status": batch.status,
    }
