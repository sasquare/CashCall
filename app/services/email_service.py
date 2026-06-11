"""
Lightweight email service. Sends via SMTP if configured; silently skips otherwise.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


def _smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)


def send_email(to: str, subject: str, body_html: str) -> None:
    if not _smtp_configured():
        logger.info("SMTP not configured — skipping email to %s: %s", to, subject)
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = to
        msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.EMAIL_FROM, [to], msg.as_string())
        logger.info("Email sent to %s: %s", to, subject)
    except Exception:
        logger.exception("Failed to send email to %s", to)


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

def notify_hod_returned(originator_email: str, submission_id: str, comment: str) -> None:
    send_email(
        to=originator_email,
        subject=f"[Cash Call] Submission {submission_id} Returned for Revision",
        body_html=f"""
        <p>Your cash call submission <strong>{submission_id}</strong> has been
        <strong>returned for revision</strong> by your HOD.</p>
        <p><strong>HOD Comment:</strong><br>{comment}</p>
        <p>Please log in to review the feedback and resubmit.</p>
        """,
    )


def notify_hod_declined(originator_email: str, submission_id: str, comment: str) -> None:
    send_email(
        to=originator_email,
        subject=f"[Cash Call] Submission {submission_id} Declined by HOD",
        body_html=f"""
        <p>Your cash call submission <strong>{submission_id}</strong> has been
        <strong>declined</strong> by your HOD.</p>
        <p><strong>Reason:</strong><br>{comment}</p>
        <p>Please log in for more details.</p>
        """,
    )
