"""
Treasury routes:
  GET  /treasury/queue                        — CEO-approved submissions
  GET  /treasury/report                       — payments KPI dashboard
  GET  /treasury/submissions/{id}             — payment detail view
  POST /treasury/submissions/{id}/update      — update payment status
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.constants import MONTH_NAMES, TREASURY_PAYMENT_STATUSES
from app.database import get_db
from app.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.submission import Submission
from app.models.user import User
from app.services.submission_service import category_usd_totals, adjust_category_budget

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


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

@router.get("/queue", response_class=HTMLResponse)
async def treasury_queue(
    request: Request,
    current_user: User = Depends(require_role("treasury")),
    db: Session = Depends(get_db),
):
    pending = (
        db.query(Submission)
        .filter(Submission.status == "pending_treasury_payment")
        .order_by(Submission.ceo_decided_at.asc())
        .all()
    )
    paid = (
        db.query(Submission)
        .filter(Submission.status == "paid")
        .order_by(Submission.treasury_updated_at.desc())
        .limit(30)
        .all()
    )
    other_statuses = (
        db.query(Submission)
        .filter(
            Submission.treasury_payment_status.isnot(None),
            Submission.status != "paid",
            Submission.status != "pending_treasury_payment",
        )
        .order_by(Submission.treasury_updated_at.desc())
        .limit(20)
        .all()
    )
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "treasury/queue.html",
        _ctx(
            request,
            user=current_user,
            pending=pending,
            paid=paid,
            other_statuses=other_statuses,
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

    def _active_usd(sub: Submission) -> float:
        return float(sum(li.equivalent_usd for li in sub.line_items if not li.cfo_deferred))

    # Currently awaiting payment — always-current queue snapshot, not period-filtered.
    awaiting = (
        db.query(Submission)
        .filter(Submission.status == "pending_treasury_payment")
        .all()
    )
    awaiting_count = len(awaiting)
    awaiting_usd = sum(_active_usd(s) for s in awaiting)

    # Everything Treasury actually acted on this period.
    period_subs = (
        db.query(Submission)
        .filter(
            Submission.treasury_updated_at >= period_start,
            Submission.treasury_updated_at < period_end,
        )
        .all()
    )

    paid_subs = [s for s in period_subs if s.treasury_payment_status == "paid"]
    paid_count = len(paid_subs)
    paid_usd = sum(_active_usd(s) for s in paid_subs)

    # Payment status breakdown for the period
    status_breakdown: dict[str, dict] = {}
    for s in period_subs:
        st = s.treasury_payment_status or "unknown"
        row = status_breakdown.setdefault(st, {"count": 0, "usd": 0.0})
        row["count"] += 1
        row["usd"] += _active_usd(s)
    status_breakdown = dict(sorted(status_breakdown.items(), key=lambda kv: kv[1]["usd"], reverse=True))

    # Currency exposure of what was actually paid this period
    currency_exposure: dict[str, dict] = {}
    for s in paid_subs:
        for li in s.line_items:
            if li.cfo_deferred:
                continue
            row = currency_exposure.setdefault(li.currency, {"original_total": 0.0, "usd_total": 0.0, "count": 0})
            row["original_total"] += float(li.original_amount)
            row["usd_total"] += float(li.equivalent_usd)
            row["count"] += 1
    currency_exposure = dict(sorted(currency_exposure.items(), key=lambda kv: kv[1]["usd_total"], reverse=True))

    # Average days from CEO approval to payment
    cycle_days = [
        (s.treasury_updated_at - s.ceo_decided_at).total_seconds() / 86400
        for s in paid_subs
        if s.ceo_decided_at and s.treasury_updated_at
    ]
    avg_cycle_days = round(sum(cycle_days) / len(cycle_days), 1) if cycle_days else None

    recent_paid = sorted(paid_subs, key=lambda s: s.treasury_updated_at or datetime.min, reverse=True)[:20]

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
        total_actioned=len(period_subs),
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
        ),
    )


# ---------------------------------------------------------------------------
# Update payment status
# ---------------------------------------------------------------------------

@router.post("/submissions/{submission_id}/update", response_class=HTMLResponse)
async def treasury_update(
    request: Request,
    submission_id: str,
    payment_status: str = Form(...),
    comment: str = Form(""),
    current_user: User = Depends(require_role("treasury")),
    db: Session = Depends(get_db),
):
    if payment_status not in TREASURY_PAYMENT_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid payment status.")

    sub = _get_sub(submission_id, db)
    if sub.status not in ("pending_treasury_payment", "paid") and sub.ceo_decision != "approved":
        raise HTTPException(status_code=409, detail="Submission has not been approved for payment.")
    now = datetime.now(timezone.utc)

    prev_status = sub.treasury_payment_status or "none"

    sub.treasury_payment_status = payment_status
    sub.treasury_comment = comment.strip() or None
    sub.treasury_updated_at = now
    sub.treasury_updated_by = current_user.id

    if payment_status == "paid":
        sub.status = "paid"
    else:
        sub.status = "pending_treasury_payment"

    if payment_status == "paid" and prev_status != "paid":
        active_items = [li for li in sub.line_items if not li.cfo_deferred]
        for category, amount in category_usd_totals(active_items).items():
            adjust_category_budget(category, sub.cost_type, sub.month, sub.year, db, delta_paid=amount)
    elif payment_status != "paid" and prev_status == "paid":
        active_items = [li for li in sub.line_items if not li.cfo_deferred]
        for category, amount in category_usd_totals(active_items).items():
            adjust_category_budget(category, sub.cost_type, sub.month, sub.year, db, delta_paid=-amount)

    db.add(AuditLog(
        submission_id=sub.id,
        action="treasury_status_updated",
        outcome=payment_status,
        performed_by=current_user.id,
        notes=f"Payment status changed from '{prev_status}' to '{payment_status}' "
              f"by {current_user.display_name}."
              + (f" Note: {comment.strip()}" if comment.strip() else ""),
    ))
    db.commit()
    return RedirectResponse(url=f"/treasury/submissions/{submission_id}?action=updated", status_code=303)
