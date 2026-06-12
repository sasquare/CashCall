"""
CEO approval routes:
  GET  /ceo/queue                      — submissions pending CEO decision
  GET  /ceo/submissions/{id}           — review detail
  POST /ceo/submissions/{id}/approve   — approve → pending_treasury
  POST /ceo/submissions/{id}/decline   — decline
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

router = APIRouter(prefix="/ceo", tags=["ceo"])


def _templates(request: Request):
    from app.main import templates
    return templates


def _ctx(request: Request, **kw):
    return {"request": request, **kw}


def _get_sub(submission_id: str, db: Session) -> Submission:
    sub = db.query(Submission).filter(Submission.submission_id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    return sub


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

@router.get("/queue", response_class=HTMLResponse)
async def ceo_queue(
    request: Request,
    current_user: User = Depends(require_role("ceo")),
    db: Session = Depends(get_db),
):
    pending = (
        db.query(Submission)
        .filter(Submission.status == "pending_ceo")
        .order_by(Submission.created_at.asc())
        .all()
    )
    reviewed = (
        db.query(Submission)
        .filter(Submission.ceo_decision.in_(["approved", "declined"]))
        .order_by(Submission.ceo_decided_at.desc())
        .limit(20)
        .all()
    )
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "ceo/queue.html",
        _ctx(request, user=current_user, pending=pending, reviewed=reviewed),
    )


# ---------------------------------------------------------------------------
# Review detail
# ---------------------------------------------------------------------------

@router.get("/submissions/{submission_id}", response_class=HTMLResponse)
async def ceo_review(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("ceo")),
    db: Session = Depends(get_db),
):
    sub = _get_sub(submission_id, db)
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "ceo/review.html",
        _ctx(request, user=current_user, submission=sub),
    )


# ---------------------------------------------------------------------------
# Approve → Treasury
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/approve", response_class=HTMLResponse)
async def ceo_approve(
    request: Request,
    submission_id: str,
    comment: str = Form(""),
    current_user: User = Depends(require_role("ceo")),
    db: Session = Depends(get_db),
):
    sub = _get_sub(submission_id, db)
    if sub.status != "pending_ceo":
        raise HTTPException(status_code=409, detail="Submission is not pending CEO approval.")
    now = datetime.now(timezone.utc)

    sub.status = "pending_treasury_payment"
    sub.ceo_decision = "approved"
    sub.ceo_reason = comment.strip() or None
    sub.ceo_decided_at = now
    sub.ceo_decided_by = current_user.id

    db.add(AuditLog(
        submission_id=sub.id,
        action="ceo_approved",
        outcome="pending_treasury_payment",
        performed_by=current_user.id,
        notes=f"Approved by CEO {current_user.display_name}."
              + (f" Comment: {comment.strip()}" if comment.strip() else ""),
    ))
    db.commit()
    return RedirectResponse(url=f"/ceo/submissions/{submission_id}?action=approved", status_code=303)


# ---------------------------------------------------------------------------
# Decline
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/decline", response_class=HTMLResponse)
async def ceo_decline(
    request: Request,
    submission_id: str,
    comment: str = Form(...),
    current_user: User = Depends(require_role("ceo")),
    db: Session = Depends(get_db),
):
    if not comment.strip():
        raise HTTPException(status_code=422, detail="A reason is required when declining.")
    sub = _get_sub(submission_id, db)
    if sub.status != "pending_ceo":
        raise HTTPException(status_code=409, detail="Submission is not pending CEO approval.")
    now = datetime.now(timezone.utc)

    sub.status = "declined_by_ceo"
    sub.ceo_decision = "declined"
    sub.ceo_reason = comment.strip()
    sub.ceo_decided_at = now
    sub.ceo_decided_by = current_user.id

    db.add(AuditLog(
        submission_id=sub.id,
        action="ceo_declined",
        outcome="declined_by_ceo",
        performed_by=current_user.id,
        notes=f"Declined by CEO {current_user.display_name}. Reason: {comment.strip()}",
    ))
    db.commit()
    return RedirectResponse(url=f"/ceo/submissions/{submission_id}?action=declined", status_code=303)
