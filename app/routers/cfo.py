"""
CFO routes:
  GET  /cfo/queue                        — submissions pending CFO decision
  GET  /cfo/submissions/{id}             — review detail
  POST /cfo/submissions/{id}/approve     — approve all → pending_ceo
  POST /cfo/submissions/{id}/decline     — decline entire submission
  POST /cfo/submissions/{id}/defer       — defer selected line items; remaining go to CEO
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.constants import MONTH_NAMES
from app.database import get_db
from app.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.line_item import LineItem
from app.models.submission import Submission
from app.models.user import User

router = APIRouter(prefix="/cfo", tags=["cfo"])


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


def _assert_pending_cfo(sub: Submission) -> None:
    if sub.status != "pending_cfo":
        raise HTTPException(status_code=409, detail="Submission is not pending CFO decision.")


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

@router.get("/queue", response_class=HTMLResponse)
async def cfo_queue(
    request: Request,
    current_user: User = Depends(require_role("cfo")),
    db: Session = Depends(get_db),
):
    pending = (
        db.query(Submission)
        .filter(Submission.status == "pending_cfo")
        .order_by(Submission.created_at.asc())
        .all()
    )
    reviewed = (
        db.query(Submission)
        .filter(Submission.cfo_decision.in_(["approved", "declined", "deferred"]))
        .order_by(Submission.cfo_decided_at.desc())
        .limit(20)
        .all()
    )
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "cfo/queue.html",
        _ctx(request, user=current_user, pending=pending, reviewed=reviewed),
    )


# ---------------------------------------------------------------------------
# Review detail
# ---------------------------------------------------------------------------

@router.get("/submissions/{submission_id}", response_class=HTMLResponse)
async def cfo_review(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("cfo")),
    db: Session = Depends(get_db),
):
    sub = _get_sub(submission_id, db)
    tmpl = _templates(request)
    month_names = {v: k for k, v in MONTH_NAMES.items()}  # not used but keep for template
    return tmpl.TemplateResponse(
        "cfo/review.html",
        _ctx(
            request,
            user=current_user,
            submission=sub,
            month_names=MONTH_NAMES,
        ),
    )


# ---------------------------------------------------------------------------
# Approve all → CEO
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/approve", response_class=HTMLResponse)
async def cfo_approve(
    request: Request,
    submission_id: str,
    comment: str = Form(""),
    current_user: User = Depends(require_role("cfo")),
    db: Session = Depends(get_db),
):
    sub = _get_sub(submission_id, db)
    _assert_pending_cfo(sub)
    now = datetime.now(timezone.utc)

    sub.status = "pending_ceo"
    sub.cfo_decision = "approved"
    sub.cfo_reason = comment.strip() or None
    sub.cfo_decided_at = now
    sub.cfo_decided_by = current_user.id

    db.add(AuditLog(
        submission_id=sub.id,
        action="cfo_approved",
        outcome="pending_ceo",
        performed_by=current_user.id,
        notes=f"Approved by CFO {current_user.display_name}."
              + (f" Comment: {comment.strip()}" if comment.strip() else ""),
    ))
    db.commit()
    return RedirectResponse(url=f"/cfo/submissions/{submission_id}?action=approved", status_code=303)


# ---------------------------------------------------------------------------
# Decline
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/decline", response_class=HTMLResponse)
async def cfo_decline(
    request: Request,
    submission_id: str,
    comment: str = Form(...),
    current_user: User = Depends(require_role("cfo")),
    db: Session = Depends(get_db),
):
    if not comment.strip():
        raise HTTPException(status_code=422, detail="A reason is required when declining.")
    sub = _get_sub(submission_id, db)
    _assert_pending_cfo(sub)
    now = datetime.now(timezone.utc)

    sub.status = "declined_by_cfo"
    sub.cfo_decision = "declined"
    sub.cfo_reason = comment.strip()
    sub.cfo_decided_at = now
    sub.cfo_decided_by = current_user.id

    db.add(AuditLog(
        submission_id=sub.id,
        action="cfo_declined",
        outcome="declined_by_cfo",
        performed_by=current_user.id,
        notes=f"Declined by CFO {current_user.display_name}. Reason: {comment.strip()}",
    ))
    db.commit()
    return RedirectResponse(url=f"/cfo/submissions/{submission_id}?action=declined", status_code=303)


# ---------------------------------------------------------------------------
# Defer selected line items; remaining proceed to CEO
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/defer", response_class=HTMLResponse)
async def cfo_defer(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("cfo")),
    db: Session = Depends(get_db),
):
    form = dict(await request.form())
    reason = form.get("reason", "").strip()
    defer_to_month_raw = form.get("defer_to_month", "")

    if not reason:
        raise HTTPException(status_code=422, detail="A reason is required for deferral.")
    try:
        defer_to_month = int(defer_to_month_raw)
        if not 1 <= defer_to_month <= 12:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="A valid defer-to month (1–12) is required.")

    # Collect deferred line item IDs from form checkboxes named "defer_item_{li_id}"
    deferred_ids: set[int] = set()
    for key in form:
        if key.startswith("defer_item_") and form[key] == "on":
            try:
                deferred_ids.add(int(key.split("_")[-1]))
            except ValueError:
                pass

    sub = _get_sub(submission_id, db)
    _assert_pending_cfo(sub)

    if not deferred_ids:
        raise HTTPException(status_code=422, detail="Select at least one line item to defer.")

    all_item_ids = {item.id for item in sub.line_items}
    if deferred_ids >= all_item_ids:
        # All items deferred → entire submission deferred
        for item in sub.line_items:
            item.cfo_deferred = True
            item.cfo_defer_to_month = defer_to_month
        new_status = "deferred_by_cfo"
        outcome_note = "All line items deferred"
    else:
        # Partial deferral — defer selected, rest proceed
        for item in sub.line_items:
            if item.id in deferred_ids:
                item.cfo_deferred = True
                item.cfo_defer_to_month = defer_to_month
        new_status = "pending_ceo"
        outcome_note = f"{len(deferred_ids)} of {len(all_item_ids)} line item(s) deferred"

    now = datetime.now(timezone.utc)
    sub.status = new_status
    sub.cfo_decision = "deferred"
    sub.cfo_reason = reason
    sub.cfo_decided_at = now
    sub.cfo_decided_by = current_user.id
    sub.cfo_post_defer_to_month = defer_to_month

    db.add(AuditLog(
        submission_id=sub.id,
        action="cfo_deferred",
        outcome=new_status,
        performed_by=current_user.id,
        notes=f"CFO {current_user.display_name} deferred items to month {defer_to_month}. "
              f"{outcome_note}. Reason: {reason}",
    ))
    db.commit()
    return RedirectResponse(url=f"/cfo/submissions/{submission_id}?action=deferred", status_code=303)
