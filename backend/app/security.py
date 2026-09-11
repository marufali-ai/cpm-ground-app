"""Auth + RBAC. Authorization is enforced here, server-side — the mobile app is never
trusted as the sole authorization layer (PRD 72, 73, 113)."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User

bearer = HTTPBearer(auto_error=False)

# Permission matrix (PRD 72). "*" = all permissions.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "Technician": {
        "installation:create", "installation:update", "installation:submit",
        "installation:view:own", "evidence:create", "evidence:replace",
        "evidence:delete", "issue:create", "sync:write",
    },
    "VendorSupervisor": {"installation:view:vendor", "evidence:view", "issue:view", "timeline:view"},
    "CPM": {"installation:view:all", "evidence:view", "issue:view", "timeline:view", "audit:view"},
    "Operations": {"installation:view:all", "evidence:view", "issue:view", "timeline:view"},
    "Delivery": {"installation:view:all", "evidence:view", "issue:view", "timeline:view"},
    "Management": {"installation:view:all", "evidence:view", "issue:view", "timeline:view", "export"},
    "SystemAdministrator": {"*"},
}


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, pw_hash: str | None) -> bool:
    if not pw_hash:
        return False
    try:
        return bcrypt.checkpw(pw.encode(), pw_hash.encode())
    except ValueError:
        return False


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def token_fingerprint(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def make_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.user_id, "role": user.role, "name": user.name,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_ttl_min)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def new_refresh_secret() -> str:
    return secrets.token_urlsafe(48)


def has_permission(role: str, perm: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, set())
    return "*" in perms or perm in perms


def decode_access_token(raw: str) -> dict:
    try:
        data = jwt.decode(raw, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired. Sign in again.")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication token.")
    if data.get("typ") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type.")
    return data


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    data = decode_access_token(creds.credentials)
    user = db.get(User, data["sub"])
    if user is None or user.status != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is not active.")
    return user


def require(*perms: str):
    """Dependency: caller must hold at least one of the listed permissions."""
    def _dep(user: User = Depends(current_user)) -> User:
        if any(has_permission(user.role, p) for p in perms):
            return user
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Your role ({user.role}) is not permitted to perform this action.",
        )
    return _dep


def idempotency_key(idempotency_key: str | None = Header(default=None)) -> str | None:
    return idempotency_key
