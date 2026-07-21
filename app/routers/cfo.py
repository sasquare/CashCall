"""
CFO routes — per line item, unified Approve / Reject / Defer / Clarify:
  GET  /cfo/queue                        — items awaiting a CFO decision
  GET  /cfo/tracker                      — submissions that reached CFO stage or beyond
  GET  /cfo/submissions/{id}             — review a submission's items
  POST /cfo/submissions/{id}/items/approve — approve selected items → pending_ceo
  POST /cfo/submissions/{id}/items/reject  — reject selected items (reason required)
  POST /cfo/submissions/{id}/items/defer   — defer selected items to a future budget month
  POST /cfo/submissions/{id}/items/clarify — request clarification (item stays with CFO)

A deferred item keeps its budget reservation alive in the month it was
deferred to ("deferred_approved") until the CFO comes back and resolves it —
approving converts that reservation into a confirmed "approved_mtd" spend in
the deferred-to month; rejecting releases it outright. See
submission_service.resolve_cfo_deferred_budget.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.constants import MONTH_NAMES, REASON_PRESETS, STATUS_BADGE_COLOURS
from app.database import get_db
from app.dependencies import require_role
from app.models.line_item import LineItem
from app.models.submission import Submission
from app.models.user import User
from app.services.email_service import notify_batch_outcome
from app.services.submission_service import (
    adjust_category_budget,
    defer_budget_for_submission,
    flagged_items_for_notification,
    line_item_status_breakdown,
    release_budget_for_items,
    recompute_submission_status,
    resolve_cfo_deferred_budget,
    write_item_decision_log,
)

router = APIRouter(prefix="/cfo", tags=["cfo"])

# Every status where an item is still awaiting a CFO decision — either it
# hasn't been looked at yet, or it was deferred/clarification-requested by
# the CFO and is waiting to be resolved with a further decision.
ACTIONABLE = ("pending_cfo", "cfo_clarification_requested", "deferred_by_cfo")

# Statuses reachable only once a submission has entered (or passed) the CFO stage.
CFO_VISIBLE_STATUSES: list[str] = [
    "pending_cfo",
    "cfo_rejected",
    "deferred_by_cfo",
    "cfo_clarification_requested",
    "pending_ceo",
    "ceo_rejected",
    "ceo_deferred",
    "ceo_clarification_requested",
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


def _get_selected_items(sub: Submission, item_ids: list[int]) -> list[LineItem]:
    id_set = {i for i in item_ids}
    return [li for li in sub.line_items if li.id in id_set and li.status in ACTIONABLE]


def _notify_originator(sub: Submission, db: Session, stage_label: str) -> None:
    originator = db.query(User).filter(User.id == sub.created_by).first()
    if not originator:
        return
    breakdown = line_item_status_breakdown(sub.line_items)
    flagged = flagged_items_for_notification(sub.line_items)
    notify_batch_outcome(originator.email, sub.submission_id, stage_label, breakdown, flagged)


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
async def cfo_queue(
    request: Request,
    current_user: User = Depends(require_role("cfo")),
    db: Session = Depends(get_db),
):
    pending_subs = (
        db.query(Submission)
        .join(LineItem, LineItem.submission_id == Submission.id)
        .filter(LineItem.status.in_(ACTIONABLE))
        .distinct()
        .order_by(Submission.created_at.asc())
        .all()
    )
    pending_counts = {
        sub.id: sum(1 for li in sub.line_items if li.status == "pending_cfo")
        for sub in pending_subs
    }
    held_counts = {
        sub.id: sum(1 for li in sub.line_items if li.status in ("cfo_clarification_requested", "deferred_by_cfo"))
        for sub in pending_subs
    }

    recent_items = (
        db.query(LineItem)
        .join(Submission, LineItem.submission_id == Submission.id)
        .filter(LineItem.cfo_decided_at.isnot(None))
        .order_by(LineItem.cfo_decided_at.desc())
        .limit(20)
        .all()
    )

    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "cfo/queue.html",
        _ctx(
            request, user=current_user,
            pending=pending_subs, pending_counts=pending_counts, held_counts=held_counts,
            recent_items=recent_items,
        ),
    )


# ---------------------------------------------------------------------------
# Tracker — everything that has reached CFO or a later stage
# ---------------------------------------------------------------------------

@router.get("/tracker", response_class=HTMLResponse)
async def cfo_tracker(
    request: Request,
    current_user: User = Depends(require_role("cfo")),
    db: Session = Depends(get_db),
):
    status_filter = request.query_params.get("status", "").strip()
    search = request.query_params.get("q", "").strip()

    # Visible if the submission has AT LEAST ONE item that reached CFO or
    # beyond — checking the submission's rollup status alone would miss or
    # wrongly include "mixed" submissions where none of the items actually
    # reached the CFO.
    q = (
        db.query(Submission)
        .join(LineItem, LineItem.submission_id == Submission.id)
        .filter(LineItem.status.in_(CFO_VISIBLE_STATUSES))
        .distinct()
    )
    if status_filter and status_filter in CFO_VISIBLE_STATUSES:
        q = q.filter(Submission.line_items.any(LineItem.status == status_filter))
    if search:
        q = q.filter(Submission.submission_id.ilike(f"%{search}%"))

    submissions = q.order_by(Submission.created_at.desc()).limit(300).all()

    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "cfo/tracker.html",
        _ctx(
            request,
            user=current_user,
            submissions=submissions,
            status_filter=status_filter,
            search=search,
            all_statuses=CFO_VISIBLE_STATUSES,
            badge_colours=STATUS_BADGE_COLOURS,
        ),
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
    return tmpl.TemplateResponse(
        "cfo/review.html",
        _ctx(
            request,
            user=current_user,
            submission=sub,
            month_names=MONTH_NAMES,
            badge_colours=STATUS_BADGE_COLOURS,
            reason_presets=REASON_PRESETS,
        ),
    )


# ---------------------------------------------------------------------------
# Approve selected items → CEO
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/approve", response_class=HTMLResponse)
async def cfo_approve_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("cfo")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    comment = (form.get("comment") or "").strip()
    sub = _get_sub(submission_id, db)
    items = _get_selected_items(sub, _parse_item_ids(form))
    if not items:
        raise HTTPException(status_code=422, detail="Select at least one item to approve.")

    now = datetime.now(timezone.utc)
    previously_deferred = [li for li in items if li.status == "deferred_by_cfo"]
    for li in items:
        previous_status = li.status
        li.status = "pending_ceo"
        li.cfo_decision = "approved"
        li.cfo_reason = comment or None
        li.cfo_decided_at = now
        li.cfo_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "cfo_approved", "pending_ceo", current_user, db,
            notes=f"Approved by CFO {current_user.display_name}."
                  + (f" Comment: {comment}" if comment else ""),
            stage="cfo", previous_status=previous_status,
        )

    resolve_cfo_deferred_budget(sub, previously_deferred, db, approved=True)
    recompute_submission_status(sub)
    db.commit()
    _notify_originator(sub, db, "CFO")
    return RedirectResponse(url=f"/cfo/submissions/{submission_id}?action=approved", status_code=303)


# ---------------------------------------------------------------------------
# Reject selected items
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/reject", response_class=HTMLResponse)
async def cfo_reject_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("cfo")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    comment = (form.get("comment") or "").strip()
    if not comment:
        raise HTTPException(status_code=422, detail="A reason is required when rejecting items.")

    sub = _get_sub(submission_id, db)
    items = _get_selected_items(sub, _parse_item_ids(form))
    if not items:
        raise HTTPException(status_code=422, detail="Select at least one item to reject.")

    now = datetime.now(timezone.utc)
    previously_deferred = [li for li in items if li.status == "deferred_by_cfo"]
    non_deferred = [li for li in items if li.status != "deferred_by_cfo"]
    for li in items:
        previous_status = li.status
        li.status = "cfo_rejected"
        li.cfo_decision = "rejected"
        li.cfo_reason = comment
        li.cfo_decided_at = now
        li.cfo_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "cfo_rejected", "cfo_rejected", current_user, db,
            notes=f"Rejected by CFO {current_user.display_name}. Reason: {comment}",
            stage="cfo", previous_status=previous_status,
        )

    # Non-deferred items still hold their original "approved_mtd" reservation
    # from HOD approval — release it normally. Previously-deferred items hold
    # a separate "deferred_approved" reservation in their deferred-to month,
    # which resolve_cfo_deferred_budget releases instead.
    release_budget_for_items(sub, non_deferred, db)
    resolve_cfo_deferred_budget(sub, previously_deferred, db, approved=False)
    recompute_submission_status(sub)
    db.commit()
    _notify_originator(sub, db, "CFO")
    return RedirectResponse(url=f"/cfo/submissions/{submission_id}?action=rejected", status_code=303)


# ---------------------------------------------------------------------------
# Defer selected items to a future month
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/defer", response_class=HTMLResponse)
async def cfo_defer_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("cfo")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    reason = (form.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A reason is required for deferral.")
    try:
        defer_to_month = int(form.get("defer_to_month", ""))
        if not 1 <= defer_to_month <= 12:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="A valid defer-to month (1–12) is required.")

    sub = _get_sub(submission_id, db)
    items = _get_selected_items(sub, _parse_item_ids(form))
    if not items:
        raise HTTPException(status_code=422, detail="Select at least one item to defer.")

    now = datetime.now(timezone.utc)
    # An item can be re-deferred to a different month; move its existing
    # "deferred_approved" reservation out of the old target month first so
    # it isn't double-counted, then re-reserve in the new target month below.
    already_deferred = [li for li in items if li.status == "deferred_by_cfo" and li.cfo_defer_to_month]
    for li in already_deferred:
        resolve_cfo_deferred_budget(sub, [li], db, approved=False)

    for li in items:
        previous_status = li.status
        li.status = "deferred_by_cfo"
        li.cfo_decision = "deferred"
        li.cfo_reason = reason
        li.cfo_decided_at = now
        li.cfo_decided_by = current_user.id
        li.cfo_deferred = True
        li.cfo_defer_to_month = defer_to_month
        write_item_decision_log(
            sub, li, "cfo_deferred", "deferred_by_cfo", current_user, db,
            notes=f"CFO {current_user.display_name} deferred to month {defer_to_month}. Reason: {reason}",
            stage="cfo", previous_status=previous_status,
        )

    # Items freshly deferred from pending_cfo/cfo_clarification_requested
    # still hold their original approved_mtd reservation — move it. Items
    # being re-deferred were already released above, so only reserve them.
    fresh = [li for li in items if li not in already_deferred]
    defer_budget_for_submission(sub, fresh, defer_to_month, db)
    for li in already_deferred:
        adjust_category_budget(
            li.category, sub.cost_type, defer_to_month, sub.year, db,
            delta_deferred=Decimal(str(li.equivalent_usd)),
        )
    recompute_submission_status(sub)
    db.commit()
    _notify_originator(sub, db, "CFO")
    return RedirectResponse(url=f"/cfo/submissions/{submission_id}?action=deferred", status_code=303)


# ---------------------------------------------------------------------------
# Request clarification on selected items — stays with CFO until resolved
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/clarify", response_class=HTMLResponse)
async def cfo_clarify_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("cfo")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    comment = (form.get("comment") or "").strip()
    if not comment:
        raise HTTPException(status_code=422, detail="Please describe what clarification is needed.")

    sub = _get_sub(submission_id, db)
    items = _get_selected_items(sub, _parse_item_ids(form))
    if not items:
        raise HTTPException(status_code=422, detail="Select at least one item.")

    now = datetime.now(timezone.utc)
    previously_deferred = [li for li in items if li.status == "deferred_by_cfo"]
    for li in items:
        previous_status = li.status
        li.status = "cfo_clarification_requested"
        li.cfo_decision = "clarification_requested"
        li.cfo_reason = comment
        li.cfo_decided_at = now
        li.cfo_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "cfo_clarification_requested", "cfo_clarification_requested", current_user, db,
            notes=f"Clarification requested by CFO {current_user.display_name}: {comment}",
            stage="cfo", previous_status=previous_status,
        )

    # Moving out of "deferred" back to a plain hold — release the
    # deferred-month reservation; it's simply pending again, no longer
    # earmarked for that specific future month.
    resolve_cfo_deferred_budget(sub, previously_deferred, db, approved=False)
    recompute_submission_status(sub)
    db.commit()
    _notify_originator(sub, db, "CFO")
    return RedirectResponse(url=f"/cfo/submissions/{submission_id}?action=clarify", status_code=303)
