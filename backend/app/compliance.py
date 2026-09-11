"""Evidence-compliance engine (PRD 19, 95).

Compliance is what the system determines has been captured. It is calculated
independently of the technician's declared installation status and never overrides it.
Weights are configuration, not code (app_config key 'compliance_weights').
"""
from sqlalchemy.orm import Session

from .models import AppConfig, Center, Equipment, Evidence, Installation

DEFAULT_WEIGHTS = {
    "start_selfie": 1,
    "submission_selfie": 1,
    "cctv_coverage": 4,
    "monitor_evidence": 1,
    "ups_evidence": 1,
    "router_photo": 1,
    "internet_answered": 1,
    "issue_evidence": 1,
}


def _weights(db: Session) -> dict:
    row = db.get(AppConfig, "compliance_weights")
    if row and isinstance(row.value, dict):
        return {**DEFAULT_WEIGHTS, **row.value}
    return dict(DEFAULT_WEIGHTS)


def compute(db: Session, inst: Installation) -> dict:
    db.flush()  # make sure just-added equipment/evidence are visible to the relationship reads
    w = _weights(db)
    center = db.get(Center, inst.center_id)
    expected = (center.expected_cctv_count or 0) if center else 0

    active = [e for e in inst.evidence if e.status == "active"]
    by_equip: dict[str, int] = {}
    types: dict[str, int] = {}
    for e in active:
        types[e.evidence_type] = types.get(e.evidence_type, 0) + 1
        if e.equipment_id:
            by_equip[e.equipment_id] = by_equip.get(e.equipment_id, 0) + 1

    cams = [q for q in inst.equipment if q.equipment_type == "CCTV"]
    cams_with_ev = sum(1 for c in cams if by_equip.get(c.equipment_id, 0) > 0)
    router = next((q for q in inst.equipment if q.equipment_type == "Router"), None)

    selfies = {e.unit_number for e in active if e.evidence_type == "Selfie"}
    issues_ok = 1.0
    if inst.issues:
        issues_ok = 1.0 if all(i.evidence_id for i in inst.issues) else 0.0

    parts = [
        {"key": "start_selfie", "label": "Start selfie", "ratio": 1.0 if "start" in selfies else 0.0},
        {"key": "submission_selfie", "label": "Submission selfie", "ratio": 1.0 if "submit" in selfies else 0.0},
        {
            "key": "cctv_coverage",
            "label": f"CCTV evidence ({cams_with_ev}/{expected or len(cams)})",
            "ratio": (min(1.0, cams_with_ev / expected) if expected else (1.0 if cams else 0.0)),
        },
        {"key": "monitor_evidence", "label": "Monitor evidence", "ratio": 1.0 if types.get("Monitor") else 0.0},
        {"key": "ups_evidence", "label": "UPS evidence", "ratio": 1.0 if types.get("UPS") else 0.0},
        {"key": "router_photo", "label": "Router photo", "ratio": 1.0 if types.get("Router") else 0.0},
        {
            "key": "internet_answered",
            "label": "Internet working answered",
            "ratio": 1.0 if (router and router.internet_working is not None) else 0.0,
        },
        {"key": "issue_evidence", "label": "All issues have evidence", "ratio": issues_ok},
    ]

    num = sum(p["ratio"] * w.get(p["key"], 0) for p in parts)
    den = sum(w.get(p["key"], 0) for p in parts) or 1
    percent = round(num / den * 100, 1)
    for p in parts:
        p["weight"] = w.get(p["key"], 0)
        p["percent"] = round(p["ratio"] * 100)
    return {
        "installation_id": inst.installation_id,
        "percent": percent,
        "expected_cctv": expected,
        "cctv_with_evidence": cams_with_ev,
        "cctv_missing": max(0, expected - cams_with_ev),
        "cctv_additional": max(0, len(cams) - expected),
        "parts": parts,
    }
