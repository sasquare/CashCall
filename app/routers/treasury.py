"""
Treasury routes — per line item:
  GET  /treasury/queue                        — items pending payment processing
  GET  /treasury/report                       — payments KPI dashboard
  GET  /treasury/submissions/{id}             — payment detail view
  POST /treasury/submissions/{id}/items/update — update payment status on selected items
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.constants import MONTH_NAMES, STATUS_BADGE_COLOURS, TREASURY_PAYMENT_STATUSES
from app.database import get_db
from app.dependencies import require_role
from app.models.line_item import LineItem
from app.models.submission import Submission
from app.models.user import User
from app.services.submission_service import (
    adjust_category_budget,
    recompute_submission_status,
    write_item_decision_log,
)

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


def _get_selected_items(sub: Submission, item_ids: list[int]) -> list[LineItem]:
    id_set = {i for i in item_ids}
    return [li for li in sub.line_items if li.id in id_set and li.status == "pending_treasury_payment"]


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
async def treasury_queue(
    request: Request,
    current_user: User = Depends(require_role("treasury")),
    db: Session = Depends(get_db),
):
    pending_subs = (
        db.query(Submission)
        .join(LineItem, LineItem.submission_id == Submission.id)
        .filter(LineItem.status == "pending_treasury_payment")
        .distinct()
        .order_by(Submission.created_at.asc())
        .all()
    )
    pending_counts = {
        sub.id: sum(1 for li in sub.line_items if li.status == "pending_treasury_payment")
        for sub in pending_subs
    }

    recent_items = (
        db.query(LineItem)
        .join(Submission, LineItem.submission_id == Submission.id)
        .filter(LineItem.treasury_updated_at.isnot(None))
        .order_by(LineItem.treasury_updated_at.desc())
        .limit(30)
        .all()
    )
    paid_items = [li for li in recent_items if li.status == "paid"][:20]
    other_items = [li for li in recent_items if li.status != "paid"][:20]

    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "treasury/queue.html",
        _ctx(
            request, user=current_user,
            pending=pending_subs, pending_counts=pending_counts,
            paid_items=paid_items, other_items=other_items,
            payment_statuses=TREASURY_PAYMENT_STATUSES,
        ),
    )


# ---------------------------------------------------------------------------
# KPI report
# ---------------------------------------------------------------------------

def _month_bounds(month: int, year: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


@router.get("/report", response_class=HTMLResponse)
async def treasury_report(
    request: Request,
    current_user: User = Depends(require_role("treasury")),
    db: Session = Depends(get_db),
):
    today = date.today()
    sel_month = int(request.query_params.get("month", today.month))
    sel_year = int(request.query_params.get("year", today.year))
    period_start, period_end = _month_bounds(sel_month, sel_year)

    # Currently awaiting payment — always-current queue snapshot, not period-filtered.
    awaiting_items = (
        db.query(LineItem)
        .filter(LineItem.status == "pending_treasury_payment")
        .all()
    )
    awaiting_count = len(awaiting_items)
    awaiting_usd = sum(float(li.equivalent_usd) for li in awaiting_items)

    # Everything Treasury actually acted on this period.
    period_items = (
        db.query(LineItem)
        .filter(
            LineItem.treasury_updated_at >= period_start,
            LineItem.treasury_updated_at < period_end,
        )
        .all()
    )

    paid_items = [li for li in period_items if li.treasury_payment_status == "paid"]
    paid_count = len(paid_items)
    paid_usd = sum(float(li.equivalent_usd) for li in paid_items)

    # Payment status breakdown for the period
    status_breakdown: dict[str, dict] = {}
    for li in period_items:
        st = li.treasury_payment_status or "unknown"
        row = status_breakdown.setdefault(st, {"count": 0, "usd": 0.0})
        row["count"] += 1
        row["usd"] += float(li.equivalent_usd)
    status_breakdown = dict(sorted(status_breakdown.items(), key=lambda kv: kv[1]["usd"], reverse=True))

    # Currency exposure of what was actually paid this period
    currency_exposure: dict[str, dict] = {}
    for li in paid_items:
        row = currency_exposure.setdefault(li.currency, {"original_total": 0.0, "usd_total": 0.0, "count": 0})
        row["original_total"] += float(li.original_amount)
        row["usd_total"] += float(li.equivalent_usd)
        row["count"] += 1
    currency_exposure = dict(sorted(currency_exposure.items(), key=lambda kv: kv[1]["usd_total"], reverse=True))

    # Average days from CEO approval to payment
    cycle_days = [
        (li.treasury_updated_at - li.ceo_decided_at).total_seconds() / 86400
        for li in paid_items
        if li.ceo_decided_at and li.treasury_updated_at
    ]
    avg_cycle_days = round(sum(cycle_days) / len(cycle_days), 1) if cycle_days else None

    recent_paid = sorted(paid_items, key=lambda li: li.treasury_updated_at or datetime.min, reverse=True)[:20]

    tmpl = _templates(request)
    return tmpl.TemplateResponse("treasury/report.html", _ctx(
        request, user=current_user,
        sel_month=sel_month, sel_year=sel_year,
        month_names=MONTH_NAMES,
        years=list(range(today.year - 1, today.year + 2)),
        awaiting_count=awaiting_count,
        awaiting_usd=awaiting_usd,
        paid_count=paid_count,
        paid_usd=paid_usd,
        total_actioned=len(period_items),
        status_breakdown=status_breakdown,
        currency_exposure=currency_exposure,
        avg_cycle_days=avg_cycle_days,
        recent_paid=recent_paid,
    ))


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
            badge_colours=STATUS_BADGE_COLOURS,
        ),
    )


# ---------------------------------------------------------------------------
# Update payment status on selected items
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/items/update", response_class=HTMLResponse)
async def treasury_update_items(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("treasury")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    payment_status = form.get("payment_status", "")
    comment = (form.get("comment") or "").strip()
    if payment_status not in TREASURY_PAYMENT_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid payment status.")

    sub = _get_sub(submission_id, db)
    items = _get_selected_items(sub, _parse_item_ids(form))
    if not items:
        raise HTTPException(status_code=422, detail="Select at least one item to update.")

    now = datetime.now(timezone.utc)
    for li in items:
        prev_status = li.treasury_payment_status or "none"
        li.treasury_payment_status = payment_status
        li.treasury_comment = comment or None
        li.treasury_updated_at = now
        li.treasury_updated_by = current_user.id
        li.status = "paid" if payment_status == "paid" else "pending_treasury_payment"

        write_item_decision_log(
            sub, li, "treasury_status_updated", payment_status, current_user, db,
            notes=f"Payment status changed from '{prev_status}' to '{payment_status}' "
                  f"by {current_user.display_name}."
                  + (f" Note: {comment}" if comment else ""),
        )

        if payment_status == "paid" and prev_status != "paid":
            adjust_category_budget(li.category, sub.cost_type, sub.month, sub.year, db, delta_paid=li.equivalent_usd)
        elif payment_status != "paid" and prev_status == "paid":
            adjust_category_budget(li.category, sub.cost_type, sub.month, sub.year, db, delta_paid=-li.equivalent_usd)

    recompute_submission_status(sub)
    db.commit()
    return RedirectResponse(url=f"/treasury/submissions/{submission_id}?action=updated", status_code=303)
