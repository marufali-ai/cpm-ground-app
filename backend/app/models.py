"""Relational model — PRD sections 65-71, 98.

User -> Installation -> {Center, Selfie/Evidence, Equipment, Issue, Submission, AuditEvent}
Audit is append-only. Evidence replacement is non-destructive (EvidenceVersion keeps history).
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt(**kw):
    return Column(DateTime(timezone=True), **kw)


# --------------------------------------------------------------------------- #
# Identity & auth (PRD 8, 66, 73)
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True)
    vendor_id = Column(String, nullable=True)
    name = Column(String, nullable=False)
    mobile_number = Column(String, unique=True, nullable=True)
    email = Column(String, unique=True, nullable=True)
    vendor_code = Column(String, unique=True, nullable=True)
    password_hash = Column(String, nullable=True)  # never plaintext (PRD 66)
    role = Column(String, nullable=False, default="Technician")
    status = Column(String, nullable=False, default="active")
    created_at = _dt(default=utcnow)
    updated_at = _dt(default=utcnow, onupdate=utcnow)
    last_login_at = _dt(nullable=True)


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"

    id = Column(String, primary_key=True)
    mobile_number = Column(String, nullable=True, index=True)
    email = Column(String, nullable=True, index=True)
    code_hash = Column(String, nullable=False)
    expires_at = _dt(nullable=False)
    consumed = Column(Boolean, default=False)
    created_at = _dt(default=utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = _dt(nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = _dt(default=utcnow)


# --------------------------------------------------------------------------- #
# Master data (PRD 10, 11) — extensible without redesign
# --------------------------------------------------------------------------- #
class Project(Base):
    __tablename__ = "projects"

    project_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    status = Column(String, default="active")
    created_at = _dt(default=utcnow)

    centers = relationship("Center", back_populates="project")


class Center(Base):
    __tablename__ = "centers"

    center_id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.project_id"), nullable=False, index=True)
    center_code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=True)
    expected_cctv_count = Column(Integer, default=0)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    state = Column(String, nullable=True)
    city = Column(String, nullable=True)
    geofence_radius_m = Column(Integer, nullable=True)  # falls back to app config
    extra = Column(JSON, default=dict)  # future fields land here (PRD 10)
    created_at = _dt(default=utcnow)

    project = relationship("Project", back_populates="centers")


# --------------------------------------------------------------------------- #
# Installation session (PRD 17, 18, 67)
# --------------------------------------------------------------------------- #
class Installation(Base):
    __tablename__ = "installations"

    installation_id = Column(String, primary_key=True)  # INS-YYYY-NNNNNN
    project_id = Column(String, ForeignKey("projects.project_id"), nullable=False)
    center_id = Column(String, ForeignKey("centers.center_id"), nullable=False, index=True)
    technician_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    client_uuid = Column(String, unique=True, nullable=True)  # idempotent create (PRD 64, 113)

    status = Column(String, nullable=False, default="Not Started")  # PRD 18
    evidence_compliance = Column(Float, default=0.0)  # PRD 19 — computed, never overrides status
    gps_status = Column(String, nullable=True)
    gps_latitude = Column(Float, nullable=True)
    gps_longitude = Column(Float, nullable=True)
    gps_accuracy = Column(Float, nullable=True)
    gps_distance_m = Column(Float, nullable=True)

    started_at = _dt(default=utcnow)
    submitted_at = _dt(nullable=True)
    created_at = _dt(default=utcnow)
    updated_at = _dt(default=utcnow, onupdate=utcnow)

    equipment = relationship("Equipment", back_populates="installation")
    evidence = relationship("Evidence", back_populates="installation")
    issues = relationship("Issue", back_populates="installation")
    submissions = relationship("Submission", back_populates="installation")


class Counter(Base):
    __tablename__ = "counters"
    key = Column(String, primary_key=True)
    value = Column(Integer, default=0)


# --------------------------------------------------------------------------- #
# Equipment (PRD 69) — CCTV / Monitor / UPS / Router / Other
# --------------------------------------------------------------------------- #
class Equipment(Base):
    __tablename__ = "equipment"
    __table_args__ = (
        UniqueConstraint("installation_id", "equipment_type", "unit_number", name="uq_unit_per_install"),
    )

    equipment_id = Column(String, primary_key=True)
    installation_id = Column(String, ForeignKey("installations.installation_id"), nullable=False, index=True)
    equipment_type = Column(String, nullable=False)
    unit_number = Column(String, nullable=False)  # technician-chosen (PRD 23)
    location = Column(String, nullable=True)
    custom_location = Column(String, nullable=True)
    serial_number = Column(String, nullable=True, index=True)  # optional (PRD 34)
    status = Column(String, default="Installed")  # PRD 27
    remarks = Column(Text, nullable=True)
    # router-only structured facts (PRD 32)
    internet_working = Column(Boolean, nullable=True)
    speed_test = Column(String, nullable=True)
    created_at = _dt(default=utcnow)
    updated_at = _dt(default=utcnow, onupdate=utcnow)

    installation = relationship("Installation", back_populates="equipment")


# --------------------------------------------------------------------------- #
# Evidence (PRD 38, 39, 68) — original + watermarked + metadata + hash
# --------------------------------------------------------------------------- #
class Evidence(Base):
    __tablename__ = "evidence"

    evidence_id = Column(String, primary_key=True)
    installation_id = Column(String, ForeignKey("installations.installation_id"), nullable=False, index=True)
    equipment_id = Column(String, ForeignKey("equipment.equipment_id"), nullable=True, index=True)
    evidence_type = Column(String, nullable=False)  # CCTV/Monitor/UPS/Router/Selfie/Issue
    unit_number = Column(String, nullable=True)
    location = Column(String, nullable=True)

    file_reference = Column(String, nullable=True)          # original captured image
    watermarked_reference = Column(String, nullable=True)   # watermarked version (PRD 39)
    file_hash = Column(String, nullable=True, index=True)   # sha-256 of original (PRD 39)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)
    duplicate_hash = Column(Boolean, default=False)         # same bytes seen elsewhere

    captured_at = _dt(nullable=True)
    uploaded_at = _dt(nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    gps_accuracy = Column(Float, nullable=True)
    gps_verified = Column(Boolean, default=False)
    gps_status = Column(String, nullable=True)
    technician_id = Column(String, ForeignKey("users.user_id"), nullable=False)

    status = Column(String, default="active")  # active / deleted / replaced
    version = Column(Integer, default=1)
    delete_reason = Column(Text, nullable=True)

    client_uuid = Column(String, unique=True, nullable=True)
    idempotency_key = Column(String, unique=True, nullable=True)

    created_at = _dt(default=utcnow)
    updated_at = _dt(default=utcnow, onupdate=utcnow)

    installation = relationship("Installation", back_populates="evidence")
    versions = relationship("EvidenceVersion", back_populates="evidence")


class EvidenceVersion(Base):
    __tablename__ = "evidence_versions"

    id = Column(String, primary_key=True)
    evidence_id = Column(String, ForeignKey("evidence.evidence_id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    file_reference = Column(String, nullable=True)
    watermarked_reference = Column(String, nullable=True)
    file_hash = Column(String, nullable=True)
    reason = Column(Text, nullable=True)  # PRD 41 — reason for replacement
    created_at = _dt(default=utcnow)

    evidence = relationship("Evidence", back_populates="versions")


# --------------------------------------------------------------------------- #
# Issues (PRD 42, 43, 70) — every issue requires evidence
# --------------------------------------------------------------------------- #
class Issue(Base):
    __tablename__ = "issues"

    issue_id = Column(String, primary_key=True)
    installation_id = Column(String, ForeignKey("installations.installation_id"), nullable=False, index=True)
    equipment_id = Column(String, ForeignKey("equipment.equipment_id"), nullable=True)
    scope = Column(String, default="center")  # center / equipment
    severity = Column(String, nullable=False)  # Critical/High/Medium/Low
    category = Column(String, nullable=True)
    description = Column(Text, nullable=False)
    evidence_id = Column(String, ForeignKey("evidence.evidence_id"), nullable=False)  # mandatory (PRD 21)
    status = Column(String, default="Open")
    created_by = Column(String, ForeignKey("users.user_id"), nullable=False)
    created_at = _dt(default=utcnow)
    updated_at = _dt(default=utcnow, onupdate=utcnow)

    installation = relationship("Installation", back_populates="issues")


# --------------------------------------------------------------------------- #
# Submission (PRD 45, 107) — immutable event
# --------------------------------------------------------------------------- #
class Submission(Base):
    __tablename__ = "submissions"

    submission_id = Column(String, primary_key=True)
    installation_id = Column(String, ForeignKey("installations.installation_id"), nullable=False, index=True)
    client_uuid = Column(String, unique=True, nullable=True)
    status_at_submission = Column(String, nullable=False)
    compliance_at_submission = Column(Float, nullable=False)
    submission_selfie_id = Column(String, ForeignKey("evidence.evidence_id"), nullable=True)
    acknowledged = Column(Boolean, default=False)
    created_by = Column(String, ForeignKey("users.user_id"), nullable=False)
    created_at = _dt(default=utcnow)

    installation = relationship("Installation", back_populates="submissions")


# --------------------------------------------------------------------------- #
# Synchronisation (PRD 49, 50, 63)
# --------------------------------------------------------------------------- #
class SyncBatch(Base):
    __tablename__ = "sync_batches"

    batch_id = Column(String, primary_key=True)
    installation_id = Column(String, ForeignKey("installations.installation_id"), nullable=False, index=True)
    device_id = Column(String, nullable=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    declared_items = Column(Integer, default=0)
    received_items = Column(Integer, default=0)
    status = Column(String, default="open")  # open / acknowledged
    created_at = _dt(default=utcnow)
    acknowledged_at = _dt(nullable=True)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key = Column(String, primary_key=True)
    route = Column(String, nullable=False)
    user_id = Column(String, nullable=True)
    status_code = Column(Integer, nullable=False)
    response_json = Column(JSON, nullable=True)
    created_at = _dt(default=utcnow)


# --------------------------------------------------------------------------- #
# Duplicate asset registry (PRD 35) — uniqueness/conflict mechanism
# --------------------------------------------------------------------------- #
class AssetRegistry(Base):
    __tablename__ = "asset_registry"

    id = Column(String, primary_key=True)
    serial_number = Column(String, nullable=False, index=True)
    equipment_type = Column(String, nullable=True)
    center_code = Column(String, nullable=True)
    installation_id = Column(String, nullable=True)
    first_seen_at = _dt(default=utcnow)


# --------------------------------------------------------------------------- #
# Audit — append only (PRD 71, 99)
# --------------------------------------------------------------------------- #
class AuditEvent(Base):
    __tablename__ = "audit_events"

    audit_id = Column(String, primary_key=True)
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    installation_id = Column(String, nullable=True, index=True)  # denormalised for timeline queries
    action = Column(String, nullable=False)  # CREATED/UPDATED/DELETED/REPLACED/SUBMITTED/SYNCED/FAILED/STATUS_CHANGED/LOGIN/LOGOUT
    performed_by = Column(String, nullable=True)
    timestamp = _dt(default=utcnow, index=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    device_id = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    extra = Column(JSON, default=dict)


# --------------------------------------------------------------------------- #
# Configurable rules (PRD 95, 116)
# --------------------------------------------------------------------------- #
class AppConfig(Base):
    __tablename__ = "app_config"
    key = Column(String, primary_key=True)
    value = Column(JSON, nullable=True)
    updated_at = _dt(default=utcnow, onupdate=utcnow)
