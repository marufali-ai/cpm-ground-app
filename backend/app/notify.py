"""Outbound notifications - currently just email OTP delivery (PRD 8).

Real SMS-to-India OTP needs DLT sender/template registration with the telecom
operators before any provider (Twilio included, via their India route) will carry
it - a multi-day process needing business KYC, not something to gate a pilot on.
Email sidesteps that entirely, so it's the real (non-dev-banner) OTP channel here.

Two send paths:
  1. Resend's HTTPS API (preferred) - works even where the host blocks outbound
     SMTP ports, which many PaaS free tiers do by default to prevent spam abuse.
  2. Plain SMTP fallback - any provider works interchangeably by changing the
     CPM_SMTP_* settings, for hosts where outbound SMTP isn't blocked.
"""
import smtplib
from email.message import EmailMessage

import httpx

from .config import settings


def _subject_and_body(code: str) -> tuple[str, str]:
    subject = f"Your CPM Ground App verification code: {code}"
    body = (
        f"Your CPM Ground App sign-in code is: {code}\n\n"
        f"This code expires in {settings.otp_ttl_min} minutes. "
        "If you didn't request this, you can ignore this email."
    )
    return subject, body


def _send_via_resend(to_email: str, code: str) -> None:
    subject, body = _subject_and_body(code)
    resp = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        json={"from": settings.email_from, "to": [to_email], "subject": subject, "text": body},
        timeout=15,
    )
    resp.raise_for_status()


def _send_via_smtp(to_email: str, code: str) -> None:
    subject, body = _subject_and_body(code)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = to_email
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(msg)


def send_otp_email(to_email: str, code: str) -> bool:
    """Returns True if actually sent, False if no email backend is configured
    (caller should fall back to the dev-banner code display in that case).
    Raises on a configured-but-failing send, so the caller can log/see why."""
    if settings.resend_api_key:
        _send_via_resend(to_email, code)
        return True
    if settings.smtp_host:
        _send_via_smtp(to_email, code)
        return True
    return False
