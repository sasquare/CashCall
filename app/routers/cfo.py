"""
CFO routes — per line item, unified Approve / Reject / Defer:
  GET  /cfo/queue                        — items pending CFO decision
  GET  /cfo/tracker                      — submissions that reached CFO stage or beyond
  GET  /cfo/submissions/{id}             — review a submission's items
  POST /cfo/submissions/{id}/items/approve — approve selected items → pending_ceo
  POST /cfo/submissions/{id}/items/reject  — reject selected items (reason required)
  POST /cfo/submissions/{id}/items/defer   — defer selected items to a future month
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.constants import MONTH_NAMES, STATUS_BADGE_COLOURS
from app.database import get_db
from app.dependencies import require_role
from app.models.line_item import LineItem
from app.models.submission import Submission
from app.models.user import User
from app.services.submission_service import (
    defer_budget_for_submission,
    release_budget_for_items,
    recompute_submission_status,
    write_item_decision_log,
)

router = APIRouter(prefix="/cfo", tags=["cfo"])

# Statuses reachable only once a submission has entered (or passed) the CFO stage.
CFO_VISIBLE_STATUSES: list[str] = [
    "pending_cfo",
    "cfo_rejected",
    "deferred_by_cfo",
    "pending_ceo",
    "ceo_rejected",
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
    return [li for li in sub.line_items if li.id in id_set and li.status == "pending_cfo"]


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
        .filter(LineItem.status == "pending_cfo")
        .distinct()
        .order_by(Submission.created_at.asc())
        .all()
    )
    pending_counts = {
        sub.id: sum(1 for li in sub.line_items if li.status == "pending_cfo")
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
            pending=pending_subs, pending_counts=pending_counts,
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
    for li in items:
        li.status = "pending_ceo"
        li.cfo_decision = "approved"
        li.cfo_reason = comment or None
        li.cfo_decided_at = now
        li.cfo_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "cfo_approved", "pending_ceo", current_user, db,
            notes=f"Approved by CFO {current_user.display_name}."
                  + (f" Comment: {comment}" if comment else ""),
        )

    recompute_submission_status(sub)
    db.commit()
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
    for li in items:
        li.status = "cfo_rejected"
        li.cfo_decision = "rejected"
        li.cfo_reason = comment
        li.cfo_decided_at = now
        li.cfo_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "cfo_rejected", "cfo_rejected", current_user, db,
            notes=f"Rejected by CFO {current_user.display_name}. Reason: {comment}",
        )

    release_budget_for_items(sub, items, db)
    recompute_submission_status(sub)
    db.commit()
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
    for li in items:
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
        )

    defer_budget_for_submission(sub, items, defer_to_month, db)
    recompute_submission_status(sub)
    db.commit()
    return RedirectResponse(url=f"/cfo/submissions/{submission_id}?action=deferred", status_code=303)
