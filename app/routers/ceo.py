"""
CEO approval routes — per line item:
  GET  /ceo/queue                      — items pending CEO decision
  GET  /ceo/submissions/{id}           — review a submission's items
  POST /ceo/submissions/{id}/items/approve — approve selected items → pending_treasury_payment
  POST /ceo/submissions/{id}/items/reject  — reject selected items (reason required)
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


def _get_selected_items(sub: Submission, item_ids: list[int]) -> list[LineItem]:
    id_set = {i for i in item_ids}
    return [li for li in sub.line_items if li.id in id_set and li.status == "pending_ceo"]


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
        .filter(LineItem.status == "pending_ceo")
        .distinct()
        .order_by(Submission.created_at.asc())
        .all()
    )
    pending_counts = {
        sub.id: sum(1 for li in sub.line_items if li.status == "pending_ceo")
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
            pending=pending_subs, pending_counts=pending_counts,
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
        _ctx(request, user=current_user, submission=sub, badge_colours=STATUS_BADGE_COLOURS),
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
        li.status = "pending_treasury_payment"
        li.ceo_decision = "approved"
        li.ceo_reason = comment or None
        li.ceo_decided_at = now
        li.ceo_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "ceo_approved", "pending_treasury_payment", current_user, db,
            notes=f"Approved by CEO {current_user.display_name}."
                  + (f" Comment: {comment}" if comment else ""),
        )

    recompute_submission_status(sub)
    db.commit()
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
        li.status = "ceo_rejected"
        li.ceo_decision = "rejected"
        li.ceo_reason = comment
        li.ceo_decided_at = now
        li.ceo_decided_by = current_user.id
        write_item_decision_log(
            sub, li, "ceo_rejected", "ceo_rejected", current_user, db,
            notes=f"Rejected by CEO {current_user.display_name}. Reason: {comment}",
        )

    release_budget_for_items(sub, items, db)
    recompute_submission_status(sub)
    db.commit()
    return RedirectResponse(url=f"/ceo/submissions/{submission_id}?action=rejected", status_code=303)
