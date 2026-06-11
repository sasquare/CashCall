"""
Treasury routes:
  GET  /treasury/queue                        — CEO-approved submissions
  GET  /treasury/submissions/{id}             — payment detail view
  POST /treasury/submissions/{id}/update      — update payment status
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.constants import TREASURY_PAYMENT_STATUSES
from app.database import get_db
from app.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.submission import Submission
from app.models.user import User

router = APIRouter(prefix="/treasury", tags=["treasury"])


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
async def treasury_queue(
    request: Request,
    current_user: User = Depends(require_role("treasury")),
    db: Session = Depends(get_db),
):
    pending = (
        db.query(Submission)
        .filter(Submission.status == "pending_treasury_payment")
        .order_by(Submission.ceo_decided_at.asc())
        .all()
    )
    paid = (
        db.query(Submission)
        .filter(Submission.status == "paid")
        .order_by(Submission.treasury_updated_at.desc())
        .limit(30)
        .all()
    )
    other_statuses = (
        db.query(Submission)
        .filter(
            Submission.treasury_payment_status.isnot(None),
            Submission.status != "paid",
            Submission.status != "pending_treasury_payment",
        )
        .order_by(Submission.treasury_updated_at.desc())
        .limit(20)
        .all()
    )
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "treasury/queue.html",
        _ctx(
            request,
            user=current_user,
            pending=pending,
            paid=paid,
            other_statuses=other_statuses,
            payment_statuses=TREASURY_PAYMENT_STATUSES,
        ),
    )


# ---------------------------------------------------------------------------
# Detail view
# ---------------------------------------------------------------------------

@router.get("/submissions/{submission_id}", response_class=HTMLResponse)
async def treasury_detail(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("treasury")),
    db: Session = Depends(get_db),
):
    sub = _get_sub(submission_id, db)
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "treasury/detail.html",
        _ctx(
            request,
            user=current_user,
            submission=sub,
            payment_statuses=TREASURY_PAYMENT_STATUSES,
        ),
    )


# ---------------------------------------------------------------------------
# Update payment status
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/update", response_class=HTMLResponse)
async def treasury_update(
    request: Request,
    submission_id: str,
    payment_status: str = Form(...),
    comment: str = Form(""),
    current_user: User = Depends(require_role("treasury")),
    db: Session = Depends(get_db),
):
    if payment_status not in TREASURY_PAYMENT_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid payment status.")

    sub = _get_sub(submission_id, db)
    if sub.status not in ("pending_treasury_payment", "paid") and sub.ceo_decision != "approved":
        raise HTTPException(status_code=409, detail="Submission has not been approved for payment.")
    now = datetime.now(timezone.utc)

    prev_status = sub.treasury_payment_status or "none"

    sub.treasury_payment_status = payment_status
    sub.treasury_comment = comment.strip() or None
    sub.treasury_updated_at = now
    sub.treasury_updated_by = current_user.id

    if payment_status == "paid":
        sub.status = "paid"
    else:
        sub.status = "pending_treasury_payment"

    db.add(AuditLog(
        submission_id=sub.id,
        action="treasury_status_updated",
        outcome=payment_status,
        performed_by=current_user.id,
        notes=f"Payment status changed from '{prev_status}' to '{payment_status}' "
              f"by {current_user.display_name}."
              + (f" Note: {comment.strip()}" if comment.strip() else ""),
    ))
    db.commit()
    return RedirectResponse(url=f"/treasury/submissions/{submission_id}?action=updated", status_code=303)
