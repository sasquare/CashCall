"""
HOD approval routes:
  GET  /hod/queue              — pending submissions for HOD's department
  GET  /hod/submissions/{id}   — review a submission
  POST /hod/submissions/{id}/approve  — approve
  POST /hod/submissions/{id}/return   — return to originator
  POST /hod/submissions/{id}/decline  — decline
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.category_budget import CategoryBudget
from app.models.line_item import LineItem
from app.models.submission import Submission
from app.models.user import User
from app.services.email_service import notify_hod_declined, notify_hod_returned

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
            Submission.hod_decision.in_(["approved", "returned", "declined"]),
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

    sub.status = "pending_finance_qc"
    sub.hod_decision = "approved"
    sub.hod_comment = comment.strip() or None
    sub.hod_decided_at = now
    sub.hod_decided_by = current_user.id

    db.add(AuditLog(
        submission_id=sub.id,
        action="hod_approved",
        outcome="pending_finance_qc",
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

    originator = db.query(User).filter(User.id == sub.creator_id).first()
    if originator:
        notify_hod_returned(originator.email, submission_id, comment.strip())

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

    originator = db.query(User).filter(User.id == sub.creator_id).first()
    if originator:
        notify_hod_declined(originator.email, submission_id, comment.strip())

    return RedirectResponse(url=f"/hod/submissions/{submission_id}?action=declined", status_code=303)


# ---------------------------------------------------------------------------
# HOD KPI Report
# ---------------------------------------------------------------------------

HOD_TERMINAL = {"ceo_approved", "paid"}
HOD_APPROVED_STATUSES = {
    "hod_approved", "pending_finance_qc", "finance_qc_approved",
    "pending_cfo", "cfo_approved", "cfo_deferred", "cfo_declined",
    "pending_ceo", "ceo_approved", "pending_treasury", "paid",
}
HOD_RETURNED_STATUSES = {"hod_returned"}
HOD_DECLINED_STATUSES = {"hod_declined"}


@router.get("/report", response_class=HTMLResponse)
async def hod_report(
    request: Request,
    current_user: User = Depends(require_role("hod")),
    db: Session = Depends(get_db),
):
    from datetime import date
    today = date.today()
    sel_month = int(request.query_params.get("month", today.month))
    sel_year = int(request.query_params.get("year", today.year))

    dept = current_user.department

    # All department submissions for selected period
    subs = (
        db.query(Submission)
        .filter(
            Submission.department == dept,
            Submission.month == sel_month,
            Submission.year == sel_year,
        )
        .all()
    )

    # Counts
    total = len(subs)
    approved = sum(1 for s in subs if s.status in HOD_APPROVED_STATUSES)
    returned = sum(1 for s in subs if s.status in HOD_RETURNED_STATUSES)
    declined = sum(1 for s in subs if s.status in HOD_DECLINED_STATUSES)
    pending = sum(1 for s in subs if s.status == "pending_hod")

    # USD spend totals
    def _usd(sub):
        return float(sum(li.equivalent_usd for li in sub.line_items))

    approved_usd = sum(_usd(s) for s in subs if s.status in HOD_APPROVED_STATUSES)
    paid_usd = sum(_usd(s) for s in subs if s.status == "paid")

    # Budget
    budget = db.query(CategoryBudget).filter(
        CategoryBudget.department == dept,
        CategoryBudget.month == sel_month,
        CategoryBudget.year == sel_year,
    ).first()
    allocation_usd = float(budget.monthly_allocation_usd) if budget else 0.0
    utilisation_pct = round((approved_usd / allocation_usd * 100), 1) if allocation_usd else None

    # Cost type breakdown
    opex_usd = sum(_usd(s) for s in subs if s.status in HOD_APPROVED_STATUSES and s.cost_type == "opex")
    capex_usd = sum(_usd(s) for s in subs if s.status in HOD_APPROVED_STATUSES and s.cost_type == "capex")

    # Request type breakdown
    urgent_count = sum(1 for s in subs if s.request_type == "urgent")
    standard_count = total - urgent_count

    # Recent submissions list (all, newest first)
    recent = sorted(subs, key=lambda s: s.created_at or datetime.min, reverse=True)[:20]

    month_names = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
                   7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}

    return _templates(request).TemplateResponse("hod/report.html", _ctx(
        request,
        user=current_user,
        dept=dept,
        sel_month=sel_month,
        sel_year=sel_year,
        month_names=month_names,
        total=total,
        approved=approved,
        returned=returned,
        declined=declined,
        pending=pending,
        approved_usd=approved_usd,
        paid_usd=paid_usd,
        allocation_usd=allocation_usd,
        utilisation_pct=utilisation_pct,
        opex_usd=opex_usd,
        capex_usd=capex_usd,
        urgent_count=urgent_count,
        standard_count=standard_count,
        recent=recent,
        over_budget=allocation_usd > 0 and approved_usd > allocation_usd,
    ))
