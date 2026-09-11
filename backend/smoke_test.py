"""End-to-end smoke test for the CPM Ground backend — no server, no network.

Exercises the full evidence chain from the PRD and prints a pass/fail line per
acceptance criterion (PRD 101-107). Run:  python smoke_test.py
"""
import os
import shutil
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("CPM_DATABASE_URL", f"sqlite:///{(HERE / 'data' / 'smoke.db').as_posix()}")
os.environ.setdefault("CPM_STORAGE_DIR", (HERE / "data" / "smoke_objects").as_posix())
os.environ.setdefault("CPM_EXPOSE_OTP", "true")

# fresh slate
for p in [HERE / "data" / "smoke.db", HERE / "data" / "smoke_objects"]:
    if p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402

# create schema + demo data without depending on the ASGI lifespan
Base.metadata.create_all(bind=engine)
with SessionLocal() as _db:
    seed(_db)

client = TestClient(app)
JPEG = b"\xff\xd8\xff\xe0" + b"CPM-EVIDENCE-DEMO" * 80 + b"\xff\xd9"  # not a real image; bytes are enough

_passed = _failed = 0


def check(name: str, ok: bool, extra: str = ""):
    global _passed, _failed
    mark = "PASS" if ok else "FAIL"
    if ok:
        _passed += 1
    else:
        _failed += 1
    print(f"  [{mark}] {name}" + (f"  — {extra}" if extra else ""))


def auth_header(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def upload_evidence(tok, inst_id, etype, unit=None, equipment_id=None, idem=None, client_uuid=None):
    data = {"installation_id": inst_id, "evidence_type": etype, "gps_verified": "true",
            "gps_status": "Verified", "latitude": "12.9716", "longitude": "77.5946", "gps_accuracy": "6"}
    if unit:
        data["unit_number"] = unit
    if equipment_id:
        data["equipment_id"] = equipment_id
    if client_uuid:
        data["client_uuid"] = client_uuid
    headers = auth_header(tok)
    if idem:
        headers["Idempotency-Key"] = idem
    return client.post("/api/v1/evidence/upload", data=data,
                       files={"file": ("cap.jpg", JPEG, "image/jpeg")}, headers=headers)


print("\nCPM Ground backend — end-to-end smoke test\n" + "=" * 48)

# --- 1. AUTH: OTP path (PRD 8, 101) -----------------------------------------
print("\nAuthentication")
r = client.post("/api/v1/auth/login", json={"mobile_number": "9876543210"})
check("OTP challenge issued", r.status_code == 200 and r.json().get("challenge_id"))
ch = r.json()
r = client.post("/api/v1/auth/verify-otp", json={"challenge_id": ch["challenge_id"], "code": ch["dev_otp"]})
check("OTP verified -> tokens", r.status_code == 200 and "access_token" in r.json())
TECH = r.json()["access_token"]
REFRESH = r.json()["refresh_token"]
check("identity established", r.json()["user"]["user_id"] == "TCH-008", r.json()["user"]["user_id"])

r = client.post("/api/v1/auth/login", json={"vendor_code": "VEND-ARC-12", "password": "demo1234"})
check("vendor-code + password path", r.status_code == 200 and "access_token" in r.json())
r = client.post("/api/v1/auth/login", json={"vendor_code": "VEND-ARC-12", "password": "wrong"})
check("bad password rejected", r.status_code == 401)
r = client.post("/api/v1/auth/refresh", json={"refresh_token": REFRESH})
check("refresh token rotates", r.status_code == 200 and r.json()["refresh_token"] != REFRESH)

# --- 2. CATALOG (PRD 10, 11) ----------------------------------------------
print("\nProjects & centers")
r = client.get("/api/v1/projects", headers=auth_header(TECH))
check("projects listed", r.status_code == 200 and len(r.json()) == 3)
r = client.get("/api/v1/projects/PRJ-01/centers", headers=auth_header(TECH))
check("centers carry expected CCTV count", any(c["expected_cctv_count"] == 24 for c in r.json()))
r = client.get("/api/v1/projects/PRJ-01/centers", headers={})
check("unauthenticated request blocked", r.status_code == 401)

# --- 3. INSTALLATION (PRD 17, 67) ---------------------------------------
print("\nInstallation session")
cuuid = str(uuid.uuid4())
r = client.post("/api/v1/installations", headers=auth_header(TECH),
                json={"project_id": "PRJ-01", "center_id": "CTR-001245", "client_uuid": cuuid,
                      "gps": {"status": "Verified", "latitude": 12.9716, "longitude": 77.5946,
                              "accuracy": 6, "distance_m": 11}})
check("installation created", r.status_code == 201 and r.json()["installation_id"].startswith("INS-"))
INST = r.json()["installation_id"]
r2 = client.post("/api/v1/installations", headers=auth_header(TECH),
                 json={"project_id": "PRJ-01", "center_id": "CTR-001245", "client_uuid": cuuid})
check("create is idempotent on client_uuid", r2.json()["installation_id"] == INST)

# --- 4. SELFIE (PRD 16) ----------------------------------------------------
print("\nStart selfie")
r = upload_evidence(TECH, INST, "Selfie", unit="start")
check("start selfie captured & stored", r.status_code == 201 and r.json()["file_hash"])
START_SELFIE = r.json()["evidence_id"]
check("watermark/metadata: GPS + technician bound", r.json()["gps_verified"] and r.json()["technician_id"] == "TCH-008")

# --- 5. CCTV (PRD 22-28, 105) -------------------------------------------
print("\nCCTV module")
r = client.post(f"/api/v1/installations/{INST}/equipment", headers=auth_header(TECH),
                json={"equipment_type": "CCTV", "unit_number": "CAM-01", "location": "Entry"})
check("camera created with custom number + location", r.status_code == 201)
CAM1 = r.json()["equipment_id"]
r = client.post(f"/api/v1/installations/{INST}/equipment", headers=auth_header(TECH),
                json={"equipment_type": "CCTV", "unit_number": "CAM-01", "location": "Exit"})
check("duplicate camera number blocked", r.status_code == 409 and r.json()["error"]["code"] == "UNIT_NUMBER_DUPLICATE")

idem = str(uuid.uuid4())
r = upload_evidence(TECH, INST, "CCTV", unit="CAM-01", equipment_id=CAM1, idem=idem)
check("camera evidence captured", r.status_code == 201)
EV_CAM1 = r.json()["evidence_id"]
r = upload_evidence(TECH, INST, "CCTV", unit="CAM-01", equipment_id=CAM1, idem=idem)
check("retry with same Idempotency-Key does not duplicate (PRD 64)",
      r.json().get("replayed") is True and r.json()["evidence_id"] == EV_CAM1)

# --- 6. Duplicate serial (PRD 35) ---------------------------------------
print("\nDuplicate asset detection")
r = client.get("/api/v1/assets/check", params={"serial": "DVR123456"}, headers=auth_header(TECH))
check("known serial flagged as duplicate", r.json()["duplicate"] is True)
r = client.post(f"/api/v1/installations/{INST}/equipment", headers=auth_header(TECH),
                json={"equipment_type": "CCTV", "unit_number": "CAM-DVR", "serial_number": "DVR123456"})
check("equipment still created but serial conflict surfaced",
      r.status_code == 201 and r.json()["serial_conflict"] is not None)

# --- 7. Monitor / UPS / Internet (PRD 30-32) --------------------------
print("\nMonitor / UPS / Internet")
for t, unit in [("Monitor", "MON-01"), ("UPS", "UPS-01")]:
    r = client.post(f"/api/v1/installations/{INST}/equipment", headers=auth_header(TECH),
                    json={"equipment_type": t, "unit_number": unit})
    eqid = r.json()["equipment_id"]
    upload_evidence(TECH, INST, t, unit=unit, equipment_id=eqid)
r = client.post(f"/api/v1/installations/{INST}/equipment", headers=auth_header(TECH),
                json={"equipment_type": "Router", "unit_number": "RTR-01"})
RTR = r.json()["equipment_id"]
upload_evidence(TECH, INST, "Router", unit="RTR-01", equipment_id=RTR)
r = client.patch(f"/api/v1/equipment/{RTR}", headers=auth_header(TECH), json={"internet_working": True})
check("internet working recorded separately from photo", r.json()["internet_working"] is True)

# --- 8. Issues (PRD 42, 106) ------------------------------------------
print("\nIssues")
r = client.post("/api/v1/issues", headers=auth_header(TECH),
                json={"installation_id": INST, "equipment_id": CAM1, "severity": "High",
                      "category": "Power issue", "description": "No PoE at Entry",
                      "evidence_id": EV_CAM1})
check("equipment issue created with evidence", r.status_code == 201)
r = client.post("/api/v1/issues", headers=auth_header(TECH),
                json={"installation_id": INST, "severity": "Low", "description": "no photo",
                      "evidence_id": "EVD-DOESNOTEXIST"})
check("issue without valid evidence rejected (PRD 21)", r.status_code == 400)

# --- 9. Compliance vs status (PRD 19) --------------------------------
print("\nCompliance engine")
r = client.get(f"/api/v1/installations/{INST}/compliance", headers=auth_header(TECH))
comp = r.json()
check("compliance computed independently", "percent" in comp and comp["expected_cctv"] == 24)
check("missing CCTV surfaced, not hidden", comp["cctv_missing"] == 23, f"{comp['cctv_missing']} missing")

# --- 10. Submission (PRD 45, 107) -----------------------------------
print("\nSubmission")
r = upload_evidence(TECH, INST, "Selfie", unit="submit")
SUBMIT_SELFIE = r.json()["evidence_id"]
r = client.post("/api/v1/sync/session", headers=auth_header(TECH),
                json={"installation_id": INST, "device_id": "DEV-TEST", "declared_items": 6})
BATCH = r.json()["batch_id"]
r = client.post(f"/api/v1/installations/{INST}/submit", headers=auth_header(TECH),
                json={"status": "Completed", "acknowledged": True,
                      "submission_selfie_evidence_id": SUBMIT_SELFIE, "client_uuid": str(uuid.uuid4())})
check("submission accepted", r.status_code == 200 and r.json()["submission_id"].startswith("SUB-"))
check("technician's status kept verbatim despite gap (PRD 19)", r.json()["status"] == "Completed")
check("completion warning data returned (missing cameras)", r.json()["cctv_missing"] == 23)
r = client.post(f"/api/v1/installations/{INST}/submit", headers=auth_header(TECH),
                json={"status": "Completed", "acknowledged": False})
check("submit without acknowledgement rejected", r.status_code == 400)

# --- 11. Sync acknowledge (PRD 50, 104) ---------------------------
print("\nSynchronisation")
r = client.post("/api/v1/sync/acknowledge", headers=auth_header(TECH), json={"batch_id": BATCH})
ack = r.json()
check("server acknowledges batch with authoritative list",
      r.status_code == 200 and ack["received_items"] == 6 and ack["declared_items"] == ack["received_items"])
check("server returns evidence ids + hashes for client reconciliation",
      len(ack["server_evidence_ids"]) == 6 and len(ack["server_hashes"]) == 6)

# --- 12. Replace / delete after submit (PRD 40, 41) --------------
print("\nEvidence lifecycle")
r = client.post(f"/api/v1/evidence/{EV_CAM1}/replace", headers=auth_header(TECH),
                data={"reason": "clearer angle"}, files={"file": ("v2.jpg", JPEG + b"v2", "image/jpeg")})
check("submitted evidence can be replaced", r.status_code == 200 and r.json()["version"] == 2)
r = client.get(f"/api/v1/evidence/{EV_CAM1}", headers=auth_header(TECH))
check("previous version retained in history", len(r.json()["versions"]) == 1 and r.json()["versions"][0]["reason"] == "clearer angle")
r = client.delete(f"/api/v1/evidence/{EV_CAM1}", params={"reason": "x"}, headers=auth_header(TECH))
check("delete blocked after submission (replace only)", r.status_code == 409)

# --- 13. Timeline & audit (PRD 91, 99) --------------------------
print("\nTimeline & audit trail")
r = client.get(f"/api/v1/installations/{INST}/timeline", headers=auth_header(TECH))
actions = {row["action"] for row in r.json()}
check("timeline is chronological & complete", {"CREATED", "SUBMITTED", "SYNCED", "REPLACED"} <= actions)

# --- 14. RBAC & stakeholder visibility (PRD 72, 93) -----------
print("\nRBAC & stakeholder visibility")
r = client.post("/api/v1/auth/login", json={"vendor_code": "CPM-MENON", "password": "demo1234"})
CPM = r.json()["access_token"]
r = client.get("/api/v1/installations", params={"submitted": "true"}, headers=auth_header(CPM))
check("CPM sees submitted installation", any(i["installation_id"] == INST for i in r.json()))
r = client.post("/api/v1/installations", headers=auth_header(CPM),
                json={"project_id": "PRJ-01", "center_id": "CTR-001245"})
check("CPM cannot create installations (server-side RBAC)", r.status_code == 403)
r = client.delete(f"/api/v1/evidence/{SUBMIT_SELFIE}", params={"reason": "x"}, headers=auth_header(CPM))
check("CPM cannot delete evidence", r.status_code == 403)

# --- 15. Signed evidence URL (PRD 74) ------------------------
print("\nEvidence access security")
r = client.get(f"/api/v1/evidence/{SUBMIT_SELFIE}", headers=auth_header(CPM))
signed = r.json()["signed_url"]
check("evidence GET returns a signed, expiring URL", signed and "sig=" in signed)
r = client.get(signed)
check("signed URL serves the bytes", r.status_code == 200 and len(r.content) > 0)
r = client.get(signed.replace("sig=", "sig=deadbeef"))
check("tampered signature rejected", r.status_code == 403)

# --- 16. Admin audit export (PRD 72, 99) --------------------
print("\nAdministration")
r = client.post("/api/v1/auth/login", json={"vendor_code": "ADMIN", "password": "admin1234"})
ADMIN = r.json()["access_token"]
r = client.get("/api/v1/admin/audit", params={"installation_id": INST}, headers=auth_header(ADMIN))
check("admin can read append-only audit log", r.status_code == 200 and len(r.json()) > 5)
r = client.get("/api/v1/admin/audit", params={"installation_id": INST, "export": "csv"}, headers=auth_header(ADMIN))
check("audit exports to CSV", r.status_code == 200 and r.headers["content-type"].startswith("text/csv"))
r = client.get("/api/v1/admin/users", headers=auth_header(TECH))
check("non-admin blocked from admin endpoints", r.status_code == 403)

print("\n" + "=" * 48)
print(f"  {_passed} passed, {_failed} failed")
print("=" * 48 + "\n")
sys.exit(1 if _failed else 0)
