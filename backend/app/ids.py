import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import Counter


def token(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(6).upper()}"


def installation_id(db: Session) -> str:
    """INS-YYYY-NNNNNN — monotonic per year, allocated under a row lock (PRD 17, 98)."""
    year = datetime.now(timezone.utc).year
    key = f"installation:{year}"
    row = db.get(Counter, key)
    if row is None:
        row = Counter(key=key, value=1244)  # start near the PRD's example (INS-2026-001245)
        db.add(row)
        db.flush()
    row.value += 1
    db.flush()
    return f"INS-{year}-{row.value:06d}"
