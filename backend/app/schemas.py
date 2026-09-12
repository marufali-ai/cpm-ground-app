"""Request/response contracts (PRD 64: every API defines request & response schema)."""
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class LoginRequest(BaseModel):
    mobile_number: str | None = None
    email: str | None = None
    vendor_code: str | None = None
    password: str | None = None

    @model_validator(mode="after")
    def _one_path(self):
        if not self.mobile_number and not self.email and not (self.vendor_code and self.password):
            raise ValueError("Provide a mobile number, an email, or a vendor code with password.")
        return self


class LoginResponse(BaseModel):
    method: str
    challenge_id: str | None = None
    dev_otp: str | None = None  # only when CPM_EXPOSE_OTP is true
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    user: dict | None = None


class VerifyOtpRequest(BaseModel):
    challenge_id: str
    code: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


# --------------------------------------------------------------------------- #
# Installations
# --------------------------------------------------------------------------- #
class GpsReading(BaseModel):
    status: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    accuracy: float | None = None
    distance_m: float | None = None


class InstallationCreate(BaseModel):
    project_id: str
    center_id: str
    client_uuid: str | None = Field(default=None, description="idempotent create key")
    gps: GpsReading | None = None
    device_id: str | None = None


class InstallationPatch(BaseModel):
    status: str | None = None  # PRD 18 controlled values
    gps: GpsReading | None = None
    device_id: str | None = None


class SubmitRequest(BaseModel):
    status: str
    acknowledged: bool = False
    submission_selfie_evidence_id: str | None = None
    client_uuid: str | None = None
    device_id: str | None = None


# --------------------------------------------------------------------------- #
# Equipment
# --------------------------------------------------------------------------- #
class EquipmentCreate(BaseModel):
    equipment_type: str
    unit_number: str
    location: str | None = None
    custom_location: str | None = None
    serial_number: str | None = None
    status: str = "Installed"
    remarks: str | None = None
    internet_working: bool | None = None
    speed_test: str | None = None


class EquipmentPatch(BaseModel):
    unit_number: str | None = None
    location: str | None = None
    custom_location: str | None = None
    serial_number: str | None = None
    status: str | None = None
    remarks: str | None = None
    internet_working: bool | None = None
    speed_test: str | None = None


# --------------------------------------------------------------------------- #
# Evidence  (multipart form is parsed in the router; this documents the fields)
# --------------------------------------------------------------------------- #
class EvidenceMeta(BaseModel):
    evidence_id: str
    installation_id: str
    equipment_id: str | None
    evidence_type: str
    unit_number: str | None
    location: str | None
    file_hash: str | None
    file_size: int | None
    duplicate_hash: bool
    captured_at: datetime | None
    uploaded_at: datetime | None
    latitude: float | None
    longitude: float | None
    gps_accuracy: float | None
    gps_verified: bool
    gps_status: str | None
    technician_id: str
    status: str
    version: int
    signed_url: str | None = None

    model_config = {"from_attributes": True}


# --------------------------------------------------------------------------- #
# Issues
# --------------------------------------------------------------------------- #
class IssueCreate(BaseModel):
    installation_id: str
    equipment_id: str | None = None
    severity: str
    category: str | None = None
    description: str
    evidence_id: str  # mandatory (PRD 21)


class IssuePatch(BaseModel):
    severity: str | None = None
    category: str | None = None
    description: str | None = None
    status: str | None = None


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #
class SyncSessionRequest(BaseModel):
    installation_id: str
    device_id: str | None = None
    declared_items: int = 0


class SyncAckRequest(BaseModel):
    batch_id: str
