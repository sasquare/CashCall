"""
Finance QC routes:
  GET  /finance/queue                        — submissions pending QC
  GET  /finance/tracker                       — submissions that reached Finance QC or beyond
  GET  /finance/submissions/{id}             — review detail
  POST /finance/submissions/{id}/approve     — pass to CFO
  POST /finance/submissions/{id}/query       — raise a query (status = qc_query_raised)
  POST /finance/submissions/{id}/return      — return to originator
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.constants import STATUS_BADGE_COLOURS
from app.database import get_db
from app.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.submission import Submission
from app.models.user import User

router = APIRouter(prefix="/finance", tags=["finance_qc"])

# Statuses reachable only once a submission has entered (or passed) Finance QC.
FINANCE_VISIBLE_STATUSES: list[str] = [
    "pending_finance_qc",
    "qc_query_raised",
    "returned_for_revision",
    "pending_cfo",
    "declined_by_cfo",
    "deferred_by_cfo",
    "pending_ceo",
    "declined_by_ceo",
    "pending_treasury_payment",
    "paid",
]


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
async def finance_queue(
    request: Request,
    current_user: User = Depends(require_role("finance_reviewer")),
    db: Session = Depends(get_db),
):
    pending = (
        db.query(Submission)
        .filter(Submission.status.in_(["pending_finance_qc", "qc_query_raised"]))
        .order_by(Submission.created_at.asc())
        .all()
    )
    reviewed = (
        db.query(Submission)
        .filter(Submission.finance_qc_status.in_(["approved", "returned"]))
        .order_by(Submission.finance_qc_at.desc())
        .limit(20)
        .all()
    )
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "finance/queue.html",
        _ctx(request, user=current_user, pending=pending, reviewed=reviewed),
    )


# ---------------------------------------------------------------------------
# Tracker — everything that has reached Finance QC or a later stage
# ---------------------------------------------------------------------------

@router.get("/tracker", response_class=HTMLResponse)
async def finance_tracker(
    request: Request,
    current_user: User = Depends(require_role("finance_reviewer")),
    db: Session = Depends(get_db),
):
    status_filter = request.query_params.get("status", "").strip()
    search = request.query_params.get("q", "").strip()

    q = db.query(Submission).filter(Submission.status.in_(FINANCE_VISIBLE_STATUSES))
    if status_filter and status_filter in FINANCE_VISIBLE_STATUSES:
        q = q.filter(Submission.status == status_filter)
    if search:
        q = q.filter(Submission.submission_id.ilike(f"%{search}%"))

    submissions = q.order_by(Submission.created_at.desc()).limit(300).all()

    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "finance/tracker.html",
        _ctx(
            request,
            user=current_user,
            submissions=submissions,
            status_filter=status_filter,
            search=search,
            all_statuses=FINANCE_VISIBLE_STATUSES,
            badge_colours=STATUS_BADGE_COLOURS,
        ),
    )


# ---------------------------------------------------------------------------
# Review detail
# ---------------------------------------------------------------------------

@router.get("/submissions/{submission_id}", response_class=HTMLResponse)
async def finance_review(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("finance_reviewer")),
    db: Session = Depends(get_db),
):
    sub = _get_sub(submission_id, db)
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "finance/review.html",
        _ctx(request, user=current_user, submission=sub),
    )


# ---------------------------------------------------------------------------
# Approve → forward to CFO
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/approve", response_class=HTMLResponse)
async def finance_approve(
    request: Request,
    submission_id: str,
    comment: str = Form(""),
    current_user: User = Depends(require_role("finance_reviewer")),
    db: Session = Depends(get_db),
):
    sub = _get_sub(submission_id, db)
    if sub.status not in ("pending_finance_qc", "qc_query_raised"):
        raise HTTPException(status_code=409, detail="Submission is not pending Finance QC.")
    now = datetime.now(timezone.utc)

    sub.status = "pending_cfo"
    sub.finance_qc_status = "approved"
    sub.finance_qc_comment = comment.strip() or None
    sub.finance_qc_at = now
    sub.finance_qc_by = current_user.id

    db.add(AuditLog(
        submission_id=sub.id,
        action="finance_qc_approved",
        outcome="pending_cfo",
        performed_by=current_user.id,
        notes=f"Finance QC cleared by {current_user.display_name}."
              + (f" Comment: {comment.strip()}" if comment.strip() else ""),
    ))
    db.commit()
    return RedirectResponse(url=f"/finance/submissions/{submission_id}?action=approved", status_code=303)


# ---------------------------------------------------------------------------
# Raise query
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/query", response_class=HTMLResponse)
async def finance_query(
    request: Request,
    submission_id: str,
    comment: str = Form(...),
    current_user: User = Depends(require_role("finance_reviewer")),
    db: Session = Depends(get_db),
):
    if not comment.strip():
        raise HTTPException(status_code=422, detail="Query details are required.")
    sub = _get_sub(submission_id, db)
    if sub.status not in ("pending_finance_qc", "qc_query_raised"):
        raise HTTPException(status_code=409, detail="Submission is not pending Finance QC.")
    now = datetime.now(timezone.utc)

    sub.status = "qc_query_raised"
    sub.finance_qc_status = "query_raised"
    sub.finance_qc_comment = comment.strip()
    sub.finance_qc_at = now
    sub.finance_qc_by = current_user.id

    db.add(AuditLog(
        submission_id=sub.id,
        action="finance_qc_query",
        outcome="qc_query_raised",
        performed_by=current_user.id,
        notes=f"Query raised by {current_user.display_name}: {comment.strip()}",
    ))
    db.commit()
    return RedirectResponse(url=f"/finance/submissions/{submission_id}?action=query", status_code=303)


# ---------------------------------------------------------------------------
# Return to originator
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/return", response_class=HTMLResponse)
async def finance_return(
    request: Request,
    submission_id: str,
    comment: str = Form(...),
    current_user: User = Depends(require_role("finance_reviewer")),
    db: Session = Depends(get_db),
):
    if not comment.strip():
        raise HTTPException(status_code=422, detail="A reason is required when returning a submission.")
    sub = _get_sub(submission_id, db)
    if sub.status not in ("pending_finance_qc", "qc_query_raised"):
        raise HTTPException(status_code=409, detail="Submission is not pending Finance QC.")
    now = datetime.now(timezone.utc)

    sub.status = "returned_for_revision"
    sub.finance_qc_status = "returned"
    sub.finance_qc_comment = comment.strip()
    sub.finance_qc_at = now
    sub.finance_qc_by = current_user.id

    db.add(AuditLog(
        submission_id=sub.id,
        action="finance_qc_returned",
        outcome="returned_for_revision",
        performed_by=current_user.id,
        notes=f"Returned by {current_user.display_name}: {comment.strip()}",
    ))
    db.commit()
    return RedirectResponse(url=f"/finance/submissions/{submission_id}?action=returned", status_code=303)
