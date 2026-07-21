"""
CEO approval routes — per line item:
  GET  /ceo/queue                      — items awaiting a CEO decision
  GET  /ceo/submissions/{id}           — review a submission's items
  POST /ceo/submissions/{id}/items/approve — approve selected items → pending_treasury_payment
  POST /ceo/submissions/{id}/items/reject  — reject selected items (reason required)
  POST /ceo/submissions/{id}/items/defer   — defer selected items (item stays with CEO)
  POST /ceo/submissions/{id}/items/clarify — request clarification (item stays with CEO)

Deferred and clarification-requested items stay actionable in the CEO's own
queue/review screen until resolved with a further decision.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.constants import REASON_PRESETS, STATUS_BADGE_COLOURS
from app.database import get_db
from app.dependencies import require_role
from app.models.line_item import LineItem
from app.models.submission import Submission
from app.models.user import User
from app.services.email_service import notify_batch_outcome
from app.services.submission_service import (
    flagged_items_for_notification,
    line_item_status_breakdown,
    release_budget_for_items,
    recompute_submission_status,
    write_item_decision_log,
)

router = APIRouter(prefix="/ceo", tags=["ceo"])

# Every status where an item is still awaiting a CEO decision — either it
# hasn't been looked at yet, or it was deferred/clarification-requested by
# the CEO and is waiting to be resolved.
ACTIONABLE = ("pending_ceo", "ceo_deferred", "ceo_clarification_requested")


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
async def ceo_queue(
    request: Request,
    current_user: User = Depends(require_role("ceo")),
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
        sub.id: sum(1 for li in sub.line_items if li.status == "pending_ceo")
        for sub in pending_subs
    }
    held_counts = {
        sub.id: sum(1 for li in sub.line_items if li.status in ("ceo_deferred", "ceo_clarification_requested"))
        for sub in pending_subs
    }

    recent_items = (
        db.query(LineItem)
        .join(Submission, LineItem.submission_id == Submission.id)
        .filter(LineItem.ceo_decided_at.isnot(None))
        .order_by(LineItem.ceo_decided_at.desc())
        .limit(20)
        .all()
    )

    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "ceo/queue.html",
        _ctx(
            request, user=current_user,
            pending=pending_subs, pending_counts=pending_counts, held_counts=held_counts,
            recent_items=recent_items,
        ),
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
        _ctx(
            request, user=current_user, submission=sub, badge_colours=STATUS_BADGE_COLOURS,
            reason_presets=REASON_PRESETS,
        ),
    )


# ---------------------------------------------------------------------------
# Approve selected items → Treasury
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/approve", response_class=HTMLResponse)
async def ceo_approve_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("ceo")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    comment = (form.get("comment") or "").strip()
    sub = _get_sub(submission_id, db)
    items = _get_selected_items(sub, _parse_item_ids(form))
    if not items:
        raise HTTPException(status_code=422, detail="Select at least one item to authorise.")

    now = datetime.now(timezone.utc)
    for li in items:
        previous_status = li.status
        li.status = "pending_treasury_payment"
        li.ceo_decision = "approved"
        li.ceo_reason = comment or None
        li.ceo_decided_at = now
        li.ceo_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "ceo_approved", "pending_treasury_payment", current_user, db,
            notes=f"Approved by CEO {current_user.display_name}."
                  + (f" Comment: {comment}" if comment else ""),
            stage="ceo", previous_status=previous_status,
        )

    recompute_submission_status(sub)
    db.commit()
    _notify_originator(sub, db, "CEO")
    return RedirectResponse(url=f"/ceo/submissions/{submission_id}?action=approved", status_code=303)


# ---------------------------------------------------------------------------
# Reject selected items
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/reject", response_class=HTMLResponse)
async def ceo_reject_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("ceo")),
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
    for li in items:
        previous_status = li.status
        li.status = "ceo_rejected"
        li.ceo_decision = "rejected"
        li.ceo_reason = comment
        li.ceo_decided_at = now
        li.ceo_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "ceo_rejected", "ceo_rejected", current_user, db,
            notes=f"Rejected by CEO {current_user.display_name}. Reason: {comment}",
            stage="ceo", previous_status=previous_status,
        )

    release_budget_for_items(sub, items, db)
    recompute_submission_status(sub)
    db.commit()
    _notify_originator(sub, db, "CEO")
    return RedirectResponse(url=f"/ceo/submissions/{submission_id}?action=rejected", status_code=303)


# ---------------------------------------------------------------------------
# Defer selected items — stays with CEO until resolved
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/defer", response_class=HTMLResponse)
async def ceo_defer_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("ceo")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    comment = (form.get("comment") or "").strip()
    if not comment:
        raise HTTPException(status_code=422, detail="A reason is required when deferring items.")

    sub = _get_sub(submission_id, db)
    items = _get_selected_items(sub, _parse_item_ids(form))
    if not items:
        raise HTTPException(status_code=422, detail="Select at least one item to defer.")

    now = datetime.now(timezone.utc)
    for li in items:
        previous_status = li.status
        li.status = "ceo_deferred"
        li.ceo_decision = "deferred"
        li.ceo_reason = comment
        li.ceo_decided_at = now
        li.ceo_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "ceo_deferred", "ceo_deferred", current_user, db,
            notes=f"Deferred by CEO {current_user.display_name}. Reason: {comment}",
            stage="ceo", previous_status=previous_status,
        )

    recompute_submission_status(sub)
    db.commit()
    _notify_originator(sub, db, "CEO")
    return RedirectResponse(url=f"/ceo/submissions/{submission_id}?action=deferred", status_code=303)


# ---------------------------------------------------------------------------
# Request clarification on selected items — stays with CEO until resolved
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/clarify", response_class=HTMLResponse)
async def ceo_clarify_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("ceo")),
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
    for li in items:
        previous_status = li.status
        li.status = "ceo_clarification_requested"
        li.ceo_decision = "clarification_requested"
        li.ceo_reason = comment
        li.ceo_decided_at = now
        li.ceo_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "ceo_clarification_requested", "ceo_clarification_requested", current_user, db,
            notes=f"Clarification requested by CEO {current_user.display_name}: {comment}",
            stage="ceo", previous_status=previous_status,
        )

    recompute_submission_status(sub)
    db.commit()
    _notify_originator(sub, db, "CEO")
    return RedirectResponse(url=f"/ceo/submissions/{submission_id}?action=clarify", status_code=303)
