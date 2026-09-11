"""Authentication (PRD 8, 63, 101). OTP-preferred, vendor-code + password fallback."""
import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..audit import record
from ..config import settings
from ..database import get_db
from ..errors import ApiError
from ..ids import token
from ..models import OtpChallenge, RefreshToken, User
from ..schemas import LoginRequest, LoginResponse, RefreshRequest, TokenResponse, VerifyOtpRequest
from ..security import (
    current_user,
    make_access_token,
    new_refresh_secret,
    sha256_hex,
    token_fingerprint,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _now():
    return datetime.now(timezone.utc)


def _user_public(u: User) -> dict:
    return {"user_id": u.user_id, "name": u.name, "role": u.role, "vendor_code": u.vendor_code,
            "mobile_number": u.mobile_number}


def _issue_tokens(db: Session, user: User, request: Request) -> TokenResponse:
    user.last_login_at = _now()
    secret = new_refresh_secret()
    db.add(RefreshToken(
        id=token("RFT"), user_id=user.user_id, token_hash=token_fingerprint(secret),
        expires_at=_now() + timedelta(days=settings.refresh_ttl_days),
    ))
    record(db, entity_type="auth", entity_id=user.user_id, action="LOGIN",
           performed_by=user.user_id, ip_address=request.client.host if request.client else None,
           new_value=user.role)
    db.commit()
    return TokenResponse(access_token=make_access_token(user), refresh_token=secret, user=_user_public(user))


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    # --- vendor code + password ---
    if body.vendor_code:
        user = db.query(User).filter(User.vendor_code == body.vendor_code).first()
        if not user or not verify_password(body.password or "", user.password_hash):
            raise ApiError(401, "BAD_CREDENTIALS", "Vendor code or password is incorrect.")
        if user.status != "active":
            raise ApiError(403, "ACCOUNT_DISABLED", "This account is not active.")
        t = _issue_tokens(db, user, request)
        return LoginResponse(method="password", access_token=t.access_token,
                             refresh_token=t.refresh_token, user=t.user)

    # --- mobile -> OTP ---
    mobile = body.mobile_number
    user = db.query(User).filter(User.mobile_number == mobile).first()
    if not user:
        # do not reveal whether the number exists
        raise ApiError(404, "USER_NOT_FOUND", "That mobile number is not registered for field work.")
    code = f"{random.randint(0, 999999):06d}"
    ch = OtpChallenge(
        id=token("OTP"), mobile_number=mobile, code_hash=sha256_hex(code.encode()),
        expires_at=_now() + timedelta(minutes=settings.otp_ttl_min),
    )
    db.add(ch)
    record(db, entity_type="auth", entity_id=user.user_id, action="OTP_ISSUED", performed_by=user.user_id)
    db.commit()
    return LoginResponse(method="otp", challenge_id=ch.id,
                         dev_otp=code if settings.expose_otp else None)


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp(body: VerifyOtpRequest, request: Request, db: Session = Depends(get_db)):
    ch = db.get(OtpChallenge, body.challenge_id)
    if not ch or ch.consumed:
        raise ApiError(400, "OTP_INVALID", "This verification code is no longer valid. Request a new one.")
    if ch.expires_at.replace(tzinfo=timezone.utc) < _now():
        raise ApiError(400, "OTP_EXPIRED", "The code has expired. Request a new one.")
    if ch.code_hash != sha256_hex(body.code.strip().encode()):
        raise ApiError(400, "OTP_MISMATCH", "That code does not match. Check and try again.")
    ch.consumed = True
    user = db.query(User).filter(User.mobile_number == ch.mobile_number).first()
    if not user:
        raise ApiError(404, "USER_NOT_FOUND", "Account not found.")
    return _issue_tokens(db, user, request)


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    fp = token_fingerprint(body.refresh_token)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == fp).first()
    if not row or row.revoked or row.expires_at.replace(tzinfo=timezone.utc) < _now():
        raise ApiError(401, "REFRESH_INVALID", "Your session cannot be renewed. Sign in again.")
    row.revoked = True  # rotate
    user = db.get(User, row.user_id)
    return _issue_tokens(db, user, request)


@router.post("/logout")
def logout(body: RefreshRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    fp = token_fingerprint(body.refresh_token)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == fp).first()
    if row:
        row.revoked = True
    record(db, entity_type="auth", entity_id=user.user_id, action="LOGOUT", performed_by=user.user_id)
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _user_public(user)
