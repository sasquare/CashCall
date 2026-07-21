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

def notify_hod_declined(originator_email: str, submission_id: str, comment: str) -> None:
    send_email(
        to=originator_email,
        subject=f"[Cash Call] Submission {submission_id} — Item(s) Rejected by HOD",
        body_html=f"""
        <p>One or more line item(s) on your cash call submission <strong>{submission_id}</strong>
        have been <strong>rejected</strong> by your HOD.</p>
        <p><strong>Reason:</strong><br>{comment}</p>
        <p>Please log in for more details.</p>
        """,
    )


def notify_batch_outcome(
    originator_email: str,
    submission_id: str,
    stage_label: str,
    breakdown: dict[str, int],
    flagged_items: list[dict],
) -> None:
    """
    Sent to the requester after ANY batch action (approve/reject/defer/
    clarify) on a multi-item submission, summarising the submission's full
    current line-item breakdown — not just the items touched in this one
    action — so the requester always sees the complete picture.

    breakdown: output of submission_service.line_item_status_breakdown().
    flagged_items: list of {"vendor": str, "status": str, "reason": str}
                   for every item currently rejected, deferred, or needing
                   clarification, so the requester knows exactly what to
                   follow up on.
    """
    total = sum(breakdown.values())
    summary_line = (
        f"{breakdown['paid'] + breakdown['in_progress']} of {total} item(s) progressing, "
        f"{breakdown['rejected']} rejected, {breakdown['deferred']} deferred, "
        f"{breakdown['needs_clarification']} awaiting clarification."
    )

    rows = ""
    for entry in flagged_items:
        rows += (
            f"<li><strong>{entry['vendor']}</strong> — "
            f"{entry['status'].replace('_', ' ').title()}: {entry['reason']}</li>"
        )
    flagged_html = f"<ul>{rows}</ul>" if rows else ""

    send_email(
        to=originator_email,
        subject=f"[Cash Call] Submission {submission_id} — Update from {stage_label}",
        body_html=f"""
        <p>Your cash call submission <strong>{submission_id}</strong> has been actioned by {stage_label}.</p>
        <p><strong>Current status:</strong> {summary_line}</p>
        {flagged_html}
        <p>Please log in for full details.</p>
        """,
    )
