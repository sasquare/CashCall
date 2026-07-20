"""
Finance QC routes — per line item:
  GET  /finance/queue                        — items pending QC
  GET  /finance/tracker                      — submissions that reached Finance QC or beyond
  GET  /finance/submissions/{id}             — review a submission's items
  POST /finance/submissions/{id}/items/approve — clear selected items for CFO
  POST /finance/submissions/{id}/items/query   — raise a query on selected items
  POST /finance/submissions/{id}/items/reject  — reject selected items (reason required)
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.constants import STATUS_BADGE_COLOURS
from app.database import get_db
from app.dependencies import require_role
from app.models.line_item import LineItem
from app.models.submission import Submission
from app.models.user import User
from app.services.submission_service import (
    release_budget_for_items,
    recompute_submission_status,
    write_item_decision_log,
)

router = APIRouter(prefix="/finance", tags=["finance_qc"])

# Statuses reachable only once a submission has entered (or passed) Finance QC.
FINANCE_VISIBLE_STATUSES: list[str] = [
    "pending_finance_qc",
    "qc_query_raised",
    "finance_rejected",
    "pending_cfo",
    "cfo_rejected",
    "deferred_by_cfo",
    "pending_ceo",
    "ceo_rejected",
    "pending_treasury_payment",
    "paid",
]

ACTIONABLE = ("pending_finance_qc", "qc_query_raised")


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
async def finance_queue(
    request: Request,
    current_user: User = Depends(require_role("finance_reviewer")),
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
        sub.id: sum(1 for li in sub.line_items if li.status in ACTIONABLE)
        for sub in pending_subs
    }
    query_counts = {
        sub.id: sum(1 for li in sub.line_items if li.status == "qc_query_raised")
        for sub in pending_subs
    }

    recent_items = (
        db.query(LineItem)
        .join(Submission, LineItem.submission_id == Submission.id)
        .filter(LineItem.finance_qc_at.isnot(None), LineItem.status.notin_(ACTIONABLE))
        .order_by(LineItem.finance_qc_at.desc())
        .limit(20)
        .all()
    )

    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "finance/queue.html",
        _ctx(
            request, user=current_user,
            pending=pending_subs, pending_counts=pending_counts, query_counts=query_counts,
            recent_items=recent_items,
        ),
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

    # Visible if the submission has AT LEAST ONE item that reached Finance QC
    # or beyond — checking the submission's rollup status alone would miss or
    # wrongly include "mixed" submissions where none of the items actually
    # touch Finance.
    q = (
        db.query(Submission)
        .join(LineItem, LineItem.submission_id == Submission.id)
        .filter(LineItem.status.in_(FINANCE_VISIBLE_STATUSES))
        .distinct()
    )
    if status_filter and status_filter in FINANCE_VISIBLE_STATUSES:
        q = q.filter(Submission.line_items.any(LineItem.status == status_filter))
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
        _ctx(request, user=current_user, submission=sub, badge_colours=STATUS_BADGE_COLOURS),
    )


# ---------------------------------------------------------------------------
# Clear selected items → forward to CFO
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/approve", response_class=HTMLResponse)
async def finance_approve_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("finance_reviewer")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    comment = (form.get("comment") or "").strip()
    sub = _get_sub(submission_id, db)
    items = _get_selected_items(sub, _parse_item_ids(form))
    if not items:
        raise HTTPException(status_code=422, detail="Select at least one item to clear.")

    now = datetime.now(timezone.utc)
    for li in items:
        li.status = "pending_cfo"
        li.finance_qc_status = "approved"
        li.finance_qc_comment = comment or None
        li.finance_qc_at = now
        li.finance_qc_by = current_user.id
        write_item_decision_log(
            sub, li, "finance_qc_approved", "pending_cfo", current_user, db,
            notes=f"Finance QC cleared by {current_user.display_name}."
                  + (f" Comment: {comment}" if comment else ""),
        )

    recompute_submission_status(sub)
    db.commit()
    return RedirectResponse(url=f"/finance/submissions/{submission_id}?action=approved", status_code=303)


# ---------------------------------------------------------------------------
# Raise query on selected items
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/query", response_class=HTMLResponse)
async def finance_query_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("finance_reviewer")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    comment = (form.get("comment") or "").strip()
    if not comment:
        raise HTTPException(status_code=422, detail="Query details are required.")

    sub = _get_sub(submission_id, db)
    items = _get_selected_items(sub, _parse_item_ids(form))
    if not items:
        raise HTTPException(status_code=422, detail="Select at least one item to query.")

    now = datetime.now(timezone.utc)
    for li in items:
        li.status = "qc_query_raised"
        li.finance_qc_status = "query_raised"
        li.finance_qc_comment = comment
        li.finance_qc_at = now
        li.finance_qc_by = current_user.id
        write_item_decision_log(
            sub, li, "finance_qc_query", "qc_query_raised", current_user, db,
            notes=f"Query raised by {current_user.display_name}: {comment}",
        )

    recompute_submission_status(sub)
    db.commit()
    return RedirectResponse(url=f"/finance/submissions/{submission_id}?action=query", status_code=303)


# ---------------------------------------------------------------------------
# Reject selected items
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/reject", response_class=HTMLResponse)
async def finance_reject_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("finance_reviewer")),
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
        li.status = "finance_rejected"
        li.finance_qc_status = "rejected"
        li.finance_qc_comment = comment
        li.finance_qc_at = now
        li.finance_qc_by = current_user.id
        write_item_decision_log(
            sub, li, "finance_qc_rejected", "finance_rejected", current_user, db,
            notes=f"Rejected by {current_user.display_name}: {comment}",
        )

    release_budget_for_items(sub, items, db)
    recompute_submission_status(sub)
    db.commit()
    return RedirectResponse(url=f"/finance/submissions/{submission_id}?action=rejected", status_code=303)
