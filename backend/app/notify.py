"""Outbound notifications - currently just email OTP delivery (PRD 8).

Real SMS-to-India OTP needs DLT sender/template registration with the telecom
operators before any provider (Twilio included, via their India route) will carry
it - a multi-day process needing business KYC, not something to gate a pilot on.
Email sidesteps that entirely, so it's the real (non-dev-banner) OTP channel here.

Uses plain SMTP so any provider works interchangeably - Gmail with an App Password,
or a transactional service's SMTP relay (Resend, SendGrid, etc.) - just by changing
the CPM_SMTP_* settings, no code change.
"""
import smtplib
from email.message import EmailMessage

from .config import settings


def send_otp_email(to_email: str, code: str) -> bool:
    """Returns True if actually sent, False if SMTP isn't configured (caller should
    fall back to the dev-banner code display in that case)."""
    if not settings.smtp_host:
        return False
    msg = EmailMessage()
    msg["Subject"] = f"Your CPM Ground App verification code: {code}"
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.set_content(
        f"Your CPM Ground App sign-in code is: {code}\n\n"
        f"This code expires in {settings.otp_ttl_min} minutes. "
        "If you didn't request this, you can ignore this email."
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(msg)
    return True
