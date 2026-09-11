"""Demo data — mirrors the mobile test client so the two line up during a pilot."""
from sqlalchemy.orm import Session

from .ids import token
from .models import AppConfig, AssetRegistry, Center, Project, User
from .security import hash_password

PROJECTS = [
    ("PRJ-01", "NEET 2026 — Phase 1", [
        ("CTR-001245", "ABC Examination Center", "12 MG Road, Bengaluru, KA", 24, 12.9716, 77.5946, "Karnataka", "Bengaluru"),
        ("CTR-001246", "Sunrise Public School", "Sector 21, Noida, UP", 16, 28.5850, 77.3260, "Uttar Pradesh", "Noida"),
        ("CTR-001247", "St. Xavier's College", "Park Street, Kolkata, WB", 32, 22.5540, 88.3520, "West Bengal", "Kolkata"),
    ]),
    ("PRJ-02", "JEE Main 2026", [
        ("CTR-002010", "Green Valley Institute", "Baner, Pune, MH", 12, 18.5590, 73.7868, "Maharashtra", "Pune"),
        ("CTR-002011", "National Convention Hall", "Banjara Hills, Hyderabad, TS", 40, 17.4126, 78.4487, "Telangana", "Hyderabad"),
    ]),
    ("PRJ-03", "State TET 2026", [
        ("CTR-003001", "District Model School", "Civil Lines, Jaipur, RJ", 8, 26.9124, 75.7873, "Rajasthan", "Jaipur"),
        ("CTR-003002", "Govt. Higher Secondary", "RS Puram, Coimbatore, TN", 20, 11.0168, 76.9558, "Tamil Nadu", "Coimbatore"),
    ]),
]

USERS = [
    dict(user_id="TCH-008", name="Ravi Kumar", role="Technician",
         mobile_number="9876543210", vendor_code="VEND-ARC-12", vendor_id="VEND-ARC",
         password="demo1234"),
    dict(user_id="TCH-021", name="Priya Nair", role="Technician",
         mobile_number="9811122233", vendor_code="VEND-ARC-21", vendor_id="VEND-ARC",
         password="demo1234"),
    dict(user_id="CPM-001", name="S. Menon (CPM)", role="CPM",
         mobile_number=None, vendor_code="CPM-MENON", password="demo1234"),
    dict(user_id="OPS-001", name="Ops Desk", role="Operations",
         mobile_number=None, vendor_code="OPS-DESK", password="demo1234"),
    dict(user_id="ADMIN-001", name="System Admin", role="SystemAdministrator",
         mobile_number=None, vendor_code="ADMIN", password="admin1234"),
]

ASSETS = [
    ("DVR123456", "CCTV", "CTR-000999"),
    ("UPS-APC-77120", "UPS", "CTR-000512"),
    ("RTR-TPL-4420", "Router", "CTR-000341"),
]

CONFIG = {
    "geofence": {"default_radius_m": 50, "gps_poor_accuracy_m": 30},
    "evidence": {"min_photos_cctv": 1, "max_photos_per_unit": 5, "jpeg_quality": 0.82},
    "session": {"timeout_min": 30},
    "camera_locations": ["Classroom", "Lab", "Control Room", "Entry", "Exit", "Corridor",
                          "Strong Room", "Frisking Area", "Staircase", "Outside / Perimeter", "Other"],
    "issue_severities": ["Critical", "High", "Medium", "Low"],
    "compliance_weights": {"start_selfie": 1, "submission_selfie": 1, "cctv_coverage": 4,
                            "monitor_evidence": 1, "ups_evidence": 1, "router_photo": 1,
                            "internet_answered": 1, "issue_evidence": 1},
}


def seed(db: Session) -> None:
    if db.query(Project).count() == 0:
        for pid, pname, centers in PROJECTS:
            db.add(Project(project_id=pid, name=pname))
            for code, name, addr, exp, lat, lng, st, city in centers:
                db.add(Center(center_id=code, project_id=pid, center_code=code, name=name,
                              address=addr, expected_cctv_count=exp, latitude=lat, longitude=lng,
                              state=st, city=city))
    if db.query(User).count() == 0:
        for u in USERS:
            data = dict(u)
            pw = data.pop("password", None)
            db.add(User(**data, password_hash=hash_password(pw) if pw else None))
    if db.query(AssetRegistry).count() == 0:
        for serial, typ, center in ASSETS:
            db.add(AssetRegistry(id=token("ASR"), serial_number=serial, equipment_type=typ, center_code=center))
    if db.query(AppConfig).count() == 0:
        for k, v in CONFIG.items():
            db.add(AppConfig(key=k, value=v))
    db.commit()
