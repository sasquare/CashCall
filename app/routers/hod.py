"""
HOD approval routes:
  GET  /hod/queue              — pending submissions for HOD's department
  GET  /hod/submissions/{id}   — review a submission
  POST /hod/submissions/{id}/approve  — approve
  POST /hod/submissions/{id}/return   — return to originator
  POST /hod/submissions/{id}/decline  — decline
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.submission import Submission
from app.models.user import User

router = APIRouter(prefix="/hod", tags=["hod"])


def _templates(request: Request):
    from app.main import templates
    return templates


def _ctx(request: Request, **kw):
    return {"request": request, **kw}


def _get_submission_for_hod(submission_id: str, hod: User, db: Session) -> Submission:
    sub = (
        db.query(Submission)
        .filter(Submission.submission_id == submission_id)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.department != hod.department:
        raise HTTPException(status_code=403, detail="This submission is not in your department")
    if sub.status != "pending_hod":
        raise HTTPException(status_code=409, detail="Submission is no longer pending HOD review")
    return sub


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

@router.get("/queue", response_class=HTMLResponse)
async def hod_queue(
    request: Request,
    current_user: User = Depends(require_role("hod")),
    db: Session = Depends(get_db),
):
    pending = (
        db.query(Submission)
        .filter(
            Submission.department == current_user.department,
            Submission.status == "pending_hod",
        )
        .order_by(Submission.created_at.asc())
        .all()
    )
    reviewed = (
        db.query(Submission)
        .filter(
            Submission.department == current_user.department,
            Submission.status.in_(["hod_approved", "hod_returned", "hod_declined"]),
        )
        .order_by(Submission.hod_decided_at.desc())
        .limit(20)
        .all()
    )
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "hod/queue.html",
        _ctx(request, user=current_user, pending=pending, reviewed=reviewed),
    )


# ---------------------------------------------------------------------------
# Review detail
# ---------------------------------------------------------------------------

@router.get("/submissions/{submission_id}", response_class=HTMLResponse)
async def hod_review(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("hod")),
    db: Session = Depends(get_db),
):
    sub = (
        db.query(Submission)
        .filter(Submission.submission_id == submission_id)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.department != current_user.department:
        raise HTTPException(status_code=403, detail="Not in your department")

    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "hod/review.html",
        _ctx(request, user=current_user, submission=sub),
    )


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/approve", response_class=HTMLResponse)
async def hod_approve(
    request: Request,
    submission_id: str,
    comment: str = Form(""),
    current_user: User = Depends(require_role("hod")),
    db: Session = Depends(get_db),
):
    sub = _get_submission_for_hod(submission_id, current_user, db)
    now = datetime.now(timezone.utc)

    sub.status = "hod_approved"
    sub.hod_decision = "approved"
    sub.hod_comment = comment.strip() or None
    sub.hod_decided_at = now
    sub.hod_decided_by = current_user.id

    db.add(AuditLog(
        submission_id=sub.id,
        action="hod_approved",
        outcome="hod_approved",
        performed_by=current_user.id,
        notes=f"HOD approved by {current_user.display_name}."
              + (f" Comment: {comment.strip()}" if comment.strip() else ""),
    ))
    db.commit()

    return RedirectResponse(url=f"/hod/submissions/{submission_id}?action=approved", status_code=303)


# ---------------------------------------------------------------------------
# Return to originator
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/return", response_class=HTMLResponse)
async def hod_return(
    request: Request,
    submission_id: str,
    comment: str = Form(...),
    current_user: User = Depends(require_role("hod")),
    db: Session = Depends(get_db),
):
    if not comment.strip():
        raise HTTPException(status_code=422, detail="A comment is required when returning a submission.")

    sub = _get_submission_for_hod(submission_id, current_user, db)
    now = datetime.now(timezone.utc)

    sub.status = "hod_returned"
    sub.hod_decision = "returned"
    sub.hod_comment = comment.strip()
    sub.hod_decided_at = now
    sub.hod_decided_by = current_user.id

    db.add(AuditLog(
        submission_id=sub.id,
        action="hod_returned",
        outcome="hod_returned",
        performed_by=current_user.id,
        notes=f"Returned by HOD {current_user.display_name}. Reason: {comment.strip()}",
    ))
    db.commit()

    return RedirectResponse(url=f"/hod/submissions/{submission_id}?action=returned", status_code=303)


# ---------------------------------------------------------------------------
# Decline
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/decline", response_class=HTMLResponse)
async def hod_decline(
    request: Request,
    submission_id: str,
    comment: str = Form(...),
    current_user: User = Depends(require_role("hod")),
    db: Session = Depends(get_db),
):
    if not comment.strip():
        raise HTTPException(status_code=422, detail="A reason is required when declining a submission.")

    sub = _get_submission_for_hod(submission_id, current_user, db)
    now = datetime.now(timezone.utc)

    sub.status = "hod_declined"
    sub.hod_decision = "declined"
    sub.hod_comment = comment.strip()
    sub.hod_decided_at = now
    sub.hod_decided_by = current_user.id

    db.add(AuditLog(
        submission_id=sub.id,
        action="hod_declined",
        outcome="hod_declined",
        performed_by=current_user.id,
        notes=f"Declined by HOD {current_user.display_name}. Reason: {comment.strip()}",
    ))
    db.commit()

    return RedirectResponse(url=f"/hod/submissions/{submission_id}?action=declined", status_code=303)
