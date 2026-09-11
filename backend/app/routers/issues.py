"""Issues — center-level or equipment-level, every one carries evidence (PRD 42, 43, 70, 106)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..audit import record
from ..database import get_db
from ..deps import assert_can_view
from ..errors import ApiError
from ..ids import token
from ..models import Evidence, Installation, Issue, User
from ..schemas import IssueCreate, IssuePatch
from ..security import current_user, require
from ..serialize import issue_dict

router = APIRouter(prefix="/issues", tags=["issues"])

SEVERITIES = {"Critical", "High", "Medium", "Low"}


@router.post("", status_code=201)
def create_issue(
    body: IssueCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require("issue:create")),
):
    inst = db.get(Installation, body.installation_id)
    if not inst:
        raise ApiError(404, "INSTALLATION_NOT_FOUND", f"No installation {body.installation_id}.")
    if inst.technician_id != user.user_id and user.role != "SystemAdministrator":
        raise ApiError(403, "FORBIDDEN", "You can only raise issues on your own installations.")
    if body.severity not in SEVERITIES:
        raise ApiError(422, "SEVERITY_INVALID", f"Severity must be one of {sorted(SEVERITIES)}.")
    ev = db.get(Evidence, body.evidence_id)
    if not ev or ev.status == "deleted" or ev.installation_id != inst.installation_id:
        raise ApiError(400, "ISSUE_EVIDENCE_REQUIRED",
                       "Every issue needs a photo captured for this installation (PRD 21).")

    iss = Issue(
        issue_id=token("ISS"), installation_id=inst.installation_id,
        equipment_id=body.equipment_id, scope="equipment" if body.equipment_id else "center",
        severity=body.severity, category=body.category, description=body.description,
        evidence_id=body.evidence_id, status="Open", created_by=user.user_id,
    )
    db.add(iss)
    record(db, entity_type="issue", entity_id=iss.issue_id, action="CREATED",
           performed_by=user.user_id, installation_id=inst.installation_id,
           new_value=f"{body.severity} / {body.category or '-'}")
    db.commit()
    return issue_dict(iss)


@router.get("/{issue_id}")
def get_issue(issue_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    iss = db.get(Issue, issue_id)
    if not iss:
        raise ApiError(404, "ISSUE_NOT_FOUND", f"No issue {issue_id}.")
    assert_can_view(user, db.get(Installation, iss.installation_id))
    return issue_dict(iss)


@router.patch("/{issue_id}")
def patch_issue(
    issue_id: str,
    body: IssuePatch,
    db: Session = Depends(get_db),
    user: User = Depends(require("issue:create", "issue:view")),
):
    iss = db.get(Issue, issue_id)
    if not iss:
        raise ApiError(404, "ISSUE_NOT_FOUND", f"No issue {issue_id}.")
    if body.severity and body.severity not in SEVERITIES:
        raise ApiError(422, "SEVERITY_INVALID", f"Severity must be one of {sorted(SEVERITIES)}.")
    before = {"severity": iss.severity, "status": iss.status}
    for f in ("severity", "category", "description", "status"):
        v = getattr(body, f)
        if v is not None:
            setattr(iss, f, v)
    record(db, entity_type="issue", entity_id=iss.issue_id, action="UPDATED",
           performed_by=user.user_id, installation_id=iss.installation_id,
           old_value=str(before), new_value=f"{iss.severity} / {iss.status}")
    db.commit()
    return issue_dict(iss)
