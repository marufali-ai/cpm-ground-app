"""Projects, centers, and the duplicate-asset check (PRD 10, 11, 35, 63)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError
from ..models import AssetRegistry, Center, Equipment, Project
from ..security import current_user

router = APIRouter(tags=["catalog"])


def _center_dict(c: Center) -> dict:
    return {
        "center_id": c.center_id, "project_id": c.project_id, "center_code": c.center_code,
        "name": c.name, "address": c.address, "expected_cctv_count": c.expected_cctv_count,
        "latitude": c.latitude, "longitude": c.longitude, "state": c.state, "city": c.city,
        "geofence_radius_m": c.geofence_radius_m, "extra": c.extra or {},
    }


@router.get("/projects")
def list_projects(db: Session = Depends(get_db), _=Depends(current_user)):
    return [{"project_id": p.project_id, "name": p.name, "status": p.status,
             "center_count": db.query(Center).filter(Center.project_id == p.project_id).count()}
            for p in db.query(Project).order_by(Project.name).all()]


@router.get("/projects/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db), _=Depends(current_user)):
    p = db.get(Project, project_id)
    if not p:
        raise ApiError(404, "PROJECT_NOT_FOUND", f"No project {project_id}.")
    return {"project_id": p.project_id, "name": p.name, "status": p.status}


@router.get("/projects/{project_id}/centers")
def list_centers(project_id: str, db: Session = Depends(get_db), _=Depends(current_user)):
    if not db.get(Project, project_id):
        raise ApiError(404, "PROJECT_NOT_FOUND", f"No project {project_id}.")
    rows = db.query(Center).filter(Center.project_id == project_id).order_by(Center.name).all()
    return [_center_dict(c) for c in rows]


@router.get("/centers/{center_id}")
def get_center(center_id: str, db: Session = Depends(get_db), _=Depends(current_user)):
    c = db.get(Center, center_id) or db.query(Center).filter(Center.center_code == center_id).first()
    if not c:
        raise ApiError(404, "CENTER_NOT_FOUND", f"No center {center_id}.")
    return _center_dict(c)


@router.get("/assets/check")
def check_serial(
    serial: str = Query(min_length=1),
    equipment_type: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(current_user),
):
    """Duplicate serial detection (PRD 35). Advisory — never silently creates a duplicate identity."""
    serial = serial.strip()
    reg = db.query(AssetRegistry).filter(AssetRegistry.serial_number.ilike(serial)).first()
    eq = (
        db.query(Equipment)
        .filter(Equipment.serial_number.ilike(serial))
        .order_by(Equipment.created_at.desc())
        .first()
    )
    conflict = None
    if reg:
        conflict = {"source": "asset_registry", "serial_number": reg.serial_number,
                    "center_code": reg.center_code, "equipment_type": reg.equipment_type,
                    "installation_id": reg.installation_id}
    elif eq:
        conflict = {"source": "installation", "serial_number": eq.serial_number,
                    "equipment_type": eq.equipment_type, "installation_id": eq.installation_id}
    return {"serial_number": serial, "duplicate": conflict is not None, "conflict": conflict}
