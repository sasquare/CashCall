"""
HOD approval routes — per line item:
  GET  /hod/queue                       — submissions with items awaiting HOD action
  GET  /hod/tracker                     — all department submissions, any status, searchable
  GET  /hod/submissions/{id}            — review a submission's items
  POST /hod/submissions/{id}/items/approve  — approve selected items
  POST /hod/submissions/{id}/items/reject   — reject selected items (reason required)
  POST /hod/submissions/{id}/items/defer    — defer selected items, stays with HOD (reason required)
  POST /hod/submissions/{id}/items/clarify  — request clarification, stays with HOD (reason required)

Deferred and clarification-requested items stay actionable in the HOD's own
queue/review screen — they never advance and never return to the requester
on their own — until the HOD resolves them with a further Approve/Reject.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.constants import REASON_PRESETS, STATUS_BADGE_COLOURS, SUBMISSION_STATUSES
from app.database import get_db
from app.dependencies import require_role
from app.models.line_item import LineItem
from app.models.submission import Submission
from app.models.user import User
from app.services.email_service import notify_batch_outcome, notify_hod_declined
from app.services.submission_service import (
    flagged_items_for_notification,
    line_item_status_breakdown,
    reserve_budget_for_items,
    recompute_submission_status,
    write_item_decision_log,
)

router = APIRouter(prefix="/hod", tags=["hod"])

# Every status where an item is still awaiting an HOD decision — either it
# hasn't been looked at yet, or it was deferred/clarification-requested by
# this same HOD and is waiting to be resolved.
ACTIONABLE = ("pending_hod", "hod_deferred", "hod_clarification_requested")


def _templates(request: Request):
    from app.main import templates
    return templates


def _ctx(request: Request, **kw):
    return {"request": request, **kw}


def _get_selected_items(sub: Submission, item_ids: list[int]) -> list[LineItem]:
    """Items belonging to this submission, currently actionable at the HOD stage."""
    id_set = {i for i in item_ids}
    return [li for li in sub.line_items if li.id in id_set and li.status in ACTIONABLE]


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
    return sub


def _parse_item_ids(form) -> list[int]:
    ids = []
    for raw in form.getlist("item_ids"):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            pass
    return ids


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

@router.get("/queue", response_class=HTMLResponse)
async def hod_queue(
    request: Request,
    current_user: User = Depends(require_role("hod")),
    db: Session = Depends(get_db),
):
    pending_subs = (
        db.query(Submission)
        .join(LineItem, LineItem.submission_id == Submission.id)
        .filter(Submission.department == current_user.department, LineItem.status.in_(ACTIONABLE))
        .distinct()
        .order_by(Submission.created_at.asc())
        .all()
    )
    pending_counts = {
        sub.id: sum(1 for li in sub.line_items if li.status == "pending_hod")
        for sub in pending_subs
    }
    held_counts = {
        sub.id: sum(1 for li in sub.line_items if li.status in ("hod_deferred", "hod_clarification_requested"))
        for sub in pending_subs
    }

    recent_items = (
        db.query(LineItem)
        .join(Submission, LineItem.submission_id == Submission.id)
        .filter(Submission.department == current_user.department, LineItem.hod_decided_at.isnot(None))
        .order_by(LineItem.hod_decided_at.desc())
        .limit(20)
        .all()
    )

    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "hod/queue.html",
        _ctx(
            request, user=current_user,
            pending=pending_subs, pending_counts=pending_counts, held_counts=held_counts,
            recent_items=recent_items,
        ),
    )


# ---------------------------------------------------------------------------
# Tracker — every department submission, any status, searchable
# ---------------------------------------------------------------------------

@router.get("/tracker", response_class=HTMLResponse)
async def hod_tracker(
    request: Request,
    current_user: User = Depends(require_role("hod")),
    db: Session = Depends(get_db),
):
    status_filter = request.query_params.get("status", "").strip()
    search = request.query_params.get("q", "").strip()

    q = db.query(Submission).filter(Submission.department == current_user.department)
    if status_filter:
        q = q.filter(Submission.status == status_filter)
    if search:
        q = q.filter(Submission.submission_id.ilike(f"%{search}%"))

    submissions = q.order_by(Submission.created_at.desc()).limit(300).all()

    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "hod/tracker.html",
        _ctx(
            request,
            user=current_user,
            submissions=submissions,
            status_filter=status_filter,
            search=search,
            all_statuses=SUBMISSION_STATUSES + ["mixed"],
            badge_colours=STATUS_BADGE_COLOURS,
        ),
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
    sub = _get_submission_for_hod(submission_id, current_user, db)
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "hod/review.html",
        _ctx(
            request, user=current_user, submission=sub, badge_colours=STATUS_BADGE_COLOURS,
            reason_presets=REASON_PRESETS,
        ),
    )


def _notify_originator(sub: Submission, db: Session, stage_label: str) -> None:
    originator = db.query(User).filter(User.id == sub.created_by).first()
    if not originator:
        return
    breakdown = line_item_status_breakdown(sub.line_items)
    flagged = flagged_items_for_notification(sub.line_items)
    notify_batch_outcome(originator.email, sub.submission_id, stage_label, breakdown, flagged)


# ---------------------------------------------------------------------------
# Approve selected items
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/approve", response_class=HTMLResponse)
async def hod_approve_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("hod")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    comment = (form.get("comment") or "").strip()
    sub = _get_submission_for_hod(submission_id, current_user, db)
    items = _get_selected_items(sub, _parse_item_ids(form))
    if not items:
        raise HTTPException(status_code=422, detail="Select at least one item to approve.")

    now = datetime.now(timezone.utc)
    for li in items:
        previous_status = li.status
        li.status = "pending_finance_qc"
        li.hod_decision = "approved"
        li.hod_comment = comment or None
        li.hod_decided_at = now
        li.hod_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "hod_approved", "pending_finance_qc", current_user, db,
            notes=f"HOD approved by {current_user.display_name}."
                  + (f" Comment: {comment}" if comment else ""),
            stage="hod", previous_status=previous_status,
        )

    reserve_budget_for_items(sub, items, db)
    recompute_submission_status(sub)
    db.commit()
    _notify_originator(sub, db, "HOD")

    return RedirectResponse(url=f"/hod/submissions/{submission_id}?action=approved", status_code=303)


# ---------------------------------------------------------------------------
# Reject selected items
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/reject", response_class=HTMLResponse)
async def hod_reject_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("hod")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    comment = (form.get("comment") or "").strip()
    if not comment:
        raise HTTPException(status_code=422, detail="A reason is required when rejecting items.")

    sub = _get_submission_for_hod(submission_id, current_user, db)
    items = _get_selected_items(sub, _parse_item_ids(form))
    if not items:
        raise HTTPException(status_code=422, detail="Select at least one item to reject.")

    now = datetime.now(timezone.utc)
    for li in items:
        previous_status = li.status
        li.status = "hod_rejected"
        li.hod_decision = "rejected"
        li.hod_comment = comment
        li.hod_decided_at = now
        li.hod_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "hod_rejected", "hod_rejected", current_user, db,
            notes=f"Rejected by HOD {current_user.display_name}. Reason: {comment}",
            stage="hod", previous_status=previous_status,
        )

    recompute_submission_status(sub)
    db.commit()

    originator = db.query(User).filter(User.id == sub.created_by).first()
    if originator:
        notify_hod_declined(originator.email, submission_id, comment)
    _notify_originator(sub, db, "HOD")

    return RedirectResponse(url=f"/hod/submissions/{submission_id}?action=rejected", status_code=303)


# ---------------------------------------------------------------------------
# Defer selected items — stays with HOD until resolved
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/defer", response_class=HTMLResponse)
async def hod_defer_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("hod")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    comment = (form.get("comment") or "").strip()
    if not comment:
        raise HTTPException(status_code=422, detail="A reason is required when deferring items.")

    sub = _get_submission_for_hod(submission_id, current_user, db)
    items = _get_selected_items(sub, _parse_item_ids(form))
    if not items:
        raise HTTPException(status_code=422, detail="Select at least one item to defer.")

    now = datetime.now(timezone.utc)
    for li in items:
        previous_status = li.status
        li.status = "hod_deferred"
        li.hod_decision = "deferred"
        li.hod_comment = comment
        li.hod_decided_at = now
        li.hod_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "hod_deferred", "hod_deferred", current_user, db,
            notes=f"Deferred by HOD {current_user.display_name}. Reason: {comment}",
            stage="hod", previous_status=previous_status,
        )

    recompute_submission_status(sub)
    db.commit()
    _notify_originator(sub, db, "HOD")

    return RedirectResponse(url=f"/hod/submissions/{submission_id}?action=deferred", status_code=303)


# ---------------------------------------------------------------------------
# Request clarification on selected items — stays with HOD until resolved
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/clarify", response_class=HTMLResponse)
async def hod_clarify_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("hod")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    comment = (form.get("comment") or "").strip()
    if not comment:
        raise HTTPException(status_code=422, detail="Please describe what clarification is needed.")

    sub = _get_submission_for_hod(submission_id, current_user, db)
    items = _get_selected_items(sub, _parse_item_ids(form))
    if not items:
        raise HTTPException(status_code=422, detail="Select at least one item.")

    now = datetime.now(timezone.utc)
    for li in items:
        previous_status = li.status
        li.status = "hod_clarification_requested"
        li.hod_decision = "clarification_requested"
        li.hod_comment = comment
        li.hod_decided_at = now
        li.hod_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "hod_clarification_requested", "hod_clarification_requested", current_user, db,
            notes=f"Clarification requested by HOD {current_user.display_name}: {comment}",
            stage="hod", previous_status=previous_status,
        )

    recompute_submission_status(sub)
    db.commit()
    _notify_originator(sub, db, "HOD")

    return RedirectResponse(url=f"/hod/submissions/{submission_id}?action=clarify", status_code=303)


# ---------------------------------------------------------------------------
# HOD KPI Report
# ---------------------------------------------------------------------------

@router.get("/report", response_class=HTMLResponse)
async def hod_report(
    request: Request,
    current_user: User = Depends(require_role("hod")),
    db: Session = Depends(get_db),
):
    today = date.today()
    sel_month = int(request.query_params.get("month", today.month))
    sel_year = int(request.query_params.get("year", today.year))

    dept = current_user.department

    subs = (
        db.query(Submission)
        .filter(
            Submission.department == dept,
            Submission.month == sel_month,
            Submission.year == sel_year,
        )
        .all()
    )
    all_items = [li for s in subs for li in s.line_items]

    held_statuses = ("hod_deferred", "hod_clarification_requested")

    total = len(all_items)
    pending = sum(1 for li in all_items if li.status == "pending_hod")
    rejected = sum(1 for li in all_items if li.status == "hod_rejected")
    held = sum(1 for li in all_items if li.status in held_statuses)
    approved_items = [li for li in all_items if li.status not in (("pending_hod", "hod_rejected") + held_statuses)]
    approved = len(approved_items)

    approved_usd = float(sum(li.equivalent_usd for li in approved_items))
    paid_usd = float(sum(li.equivalent_usd for li in all_items if li.status == "paid"))

    # Spend by category — informational only. Budgets are company-wide per
    # category, not owned by any one department, so there's no per-department
    # allocation to compare against here (see /admin/reports for that view).
    category_usd: dict[str, float] = {}
    for li in approved_items:
        category_usd[li.category] = category_usd.get(li.category, 0.0) + float(li.equivalent_usd)
    category_usd = dict(sorted(category_usd.items(), key=lambda kv: kv[1], reverse=True))

    opex_usd = sum(float(li.equivalent_usd) for li in approved_items if li.submission.cost_type == "opex")
    capex_usd = sum(float(li.equivalent_usd) for li in approved_items if li.submission.cost_type == "capex")

    urgent_count = sum(1 for s in subs if s.request_type == "urgent")
    standard_count = len(subs) - urgent_count

    recent = sorted(subs, key=lambda s: s.created_at or datetime.min, reverse=True)[:20]

    month_names = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
                   7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December"}

    return _templates(request).TemplateResponse("hod/report.html", _ctx(
        request,
        user=current_user,
        dept=dept,
        sel_month=sel_month,
        sel_year=sel_year,
        month_names=month_names,
        total_submissions=len(subs),
        total=total,
        approved=approved,
        rejected=rejected,
        pending=pending,
        held=held,
        approved_usd=approved_usd,
        paid_usd=paid_usd,
        category_usd=category_usd,
        opex_usd=opex_usd,
        capex_usd=capex_usd,
        urgent_count=urgent_count,
        standard_count=standard_count,
        recent=recent,
        badge_colours=STATUS_BADGE_COLOURS,
    ))
