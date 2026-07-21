"""
Submission business logic:
  - Submission ID generation
  - Exchange rate lookup and USD conversion
  - Budget overage check
  - Submission + line item creation + audit log write
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.constants import (
    CLARIFICATION_STATUSES,
    DEFERRED_STATUSES,
    MONTH_NAMES,
    REJECTED_STATUSES,
)
from app.models.audit_log import AuditLog
from app.models.category_budget import CategoryBudget
from app.models.exchange_rate import ExchangeRate
from app.models.line_item import LineItem
from app.models.submission import Submission
from app.models.user import User
from app.schemas.submission import LineItemIn, SubmissionIn, UrgentSubmissionIn


# ---------------------------------------------------------------------------
# Submission ID
# ---------------------------------------------------------------------------

def generate_submission_id(db: Session, year: int) -> str:
    """Generate SC-YYYY-NNNN, resetting sequence each calendar year."""
    prefix = f"SC-{year}-"
    last = (
        db.query(Submission.submission_id)
        .filter(Submission.submission_id.like(f"{prefix}%"))
        .order_by(Submission.submission_id.desc())
        .first()
    )
    seq = int(last[0].split("-")[-1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


# ---------------------------------------------------------------------------
# Exchange rates
# ---------------------------------------------------------------------------

def get_active_rate(currency: str, db: Session) -> ExchangeRate | None:
    """Return the most recently effective rate for a currency."""
    today = date.today()
    return (
        db.query(ExchangeRate)
        .filter(
            ExchangeRate.currency == currency,
            ExchangeRate.effective_from <= today,
        )
        .order_by(ExchangeRate.effective_from.desc())
        .first()
    )


def convert_to_usd(amount: Decimal, currency: str, db: Session) -> tuple[Decimal, Decimal]:
    """
    Returns (equivalent_usd, rate_used).
    Raises ValueError if no rate is found.
    """
    rate_row = get_active_rate(currency, db)
    if not rate_row:
        raise ValueError(
            f"No exchange rate found for {currency}. "
            "Please ask the IT Admin to update rates before submitting."
        )
    rate = Decimal(str(rate_row.rate_to_usd))
    if currency == "USD":
        return amount.quantize(Decimal("0.01"), ROUND_HALF_UP), rate

    # rate_to_usd = units of currency per 1 USD
    # equivalent_usd = original_amount / rate_to_usd
    equivalent = (amount / rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return equivalent, rate


# ---------------------------------------------------------------------------
# Budget — category-scoped (company-wide; NOT per department)
# ---------------------------------------------------------------------------

def category_usd_totals(line_items) -> dict[str, Decimal]:
    """Sum equivalent_usd per category across a set of line items (ORM objects or dicts)."""
    totals: dict[str, Decimal] = {}
    for li in line_items:
        category = li["category"] if isinstance(li, dict) else li.category
        amount = li["equivalent_usd"] if isinstance(li, dict) else li.equivalent_usd
        totals[category] = totals.get(category, Decimal("0")) + Decimal(str(amount))
    return totals


def get_or_create_budget(category: str, cost_type: str, month: int, year: int, db: Session) -> CategoryBudget:
    budget = (
        db.query(CategoryBudget)
        .filter(
            CategoryBudget.category == category,
            CategoryBudget.cost_type == cost_type,
            CategoryBudget.month == month,
            CategoryBudget.year == year,
        )
        .first()
    )
    if not budget:
        budget = CategoryBudget(category=category, cost_type=cost_type, month=month, year=year)
        db.add(budget)
        db.flush()
    return budget


def adjust_category_budget(
    category: str,
    cost_type: str,
    month: int,
    year: int,
    db: Session,
    delta_approved: Decimal = Decimal("0"),
    delta_paid: Decimal = Decimal("0"),
    delta_deferred: Decimal = Decimal("0"),
) -> None:
    """
    Moves the running totals on a category's budget row. Positive deltas reserve/add,
    negative deltas release. Called at every point a submission's line items change
    whether they count against the budget (HOD approval reserves; a later decline/
    return releases; CFO defer moves the reservation to the target month; Treasury
    marking paid adds to paid_mtd without releasing the approval reservation).
    """
    if not (delta_approved or delta_paid or delta_deferred):
        return
    budget = get_or_create_budget(category, cost_type, month, year, db)
    if delta_approved:
        budget.approved_mtd = Decimal(str(budget.approved_mtd)) + delta_approved
        budget.approved_ytd = Decimal(str(budget.approved_ytd)) + delta_approved
    if delta_paid:
        budget.paid_mtd = Decimal(str(budget.paid_mtd)) + delta_paid
    if delta_deferred:
        budget.deferred_approved = Decimal(str(budget.deferred_approved)) + delta_deferred


def reserve_budget_for_items(submission, line_items, db: Session) -> None:
    """Reserve (increment approved_mtd/ytd) for every category among the given items."""
    for category, amount in category_usd_totals(line_items).items():
        adjust_category_budget(
            category, submission.cost_type, submission.month, submission.year, db,
            delta_approved=amount,
        )


def release_budget_for_items(submission, line_items, db: Session) -> None:
    """Release a prior reservation for the given items (e.g. rejected downstream of HOD)."""
    for category, amount in category_usd_totals(line_items).items():
        adjust_category_budget(
            category, submission.cost_type, submission.month, submission.year, db,
            delta_approved=-amount,
        )


def recompute_submission_status(submission) -> None:
    """
    Roll up each line item's own status onto submission.status, used for
    queue/tracker/report display. "mixed" means the item statuses have
    diverged — each item's own status remains the real source of truth.
    """
    statuses = {li.status for li in submission.line_items}
    if len(statuses) == 1:
        submission.status = statuses.pop()
    elif statuses:
        submission.status = "mixed"


def write_item_decision_log(
    submission,
    line_item,
    action: str,
    outcome: str,
    performer: User,
    db: Session,
    notes: str | None = None,
    stage: str | None = None,
    previous_status: str | None = None,
) -> None:
    db.add(AuditLog(
        submission_id=submission.id,
        line_item_id=line_item.id,
        action=action,
        outcome=outcome,
        performed_by=performer.id,
        amount_usd=float(line_item.equivalent_usd),
        notes=notes,
        stage=stage,
        previous_status=previous_status,
    ))


# ---------------------------------------------------------------------------
# Status breakdown — aggregated counts for a submission's line items
# ---------------------------------------------------------------------------

def line_item_status_breakdown(line_items) -> dict[str, int]:
    """
    Buckets a set of line items into 5 human-facing categories: Paid,
    In Progress (pending at any stage), Deferred, Needs Clarification,
    Rejected. Used everywhere a "Mixed" submission needs to show what that
    actually means instead of a single opaque status word.
    """
    buckets = {"paid": 0, "in_progress": 0, "deferred": 0, "needs_clarification": 0, "rejected": 0}
    for li in line_items:
        if li.status == "paid":
            buckets["paid"] += 1
        elif li.status in REJECTED_STATUSES:
            buckets["rejected"] += 1
        elif li.status in DEFERRED_STATUSES:
            buckets["deferred"] += 1
        elif li.status in CLARIFICATION_STATUSES:
            buckets["needs_clarification"] += 1
        else:
            buckets["in_progress"] += 1
    return buckets


# ---------------------------------------------------------------------------
# CFO deferral resolution — convert a held "deferred_approved" reservation
# into either a confirmed "approved_mtd" reservation (item later approved)
# or release it entirely (item later rejected), in the month it was
# deferred to. Only applies to items that actually went through CFO defer;
# ignored for everything else.
# ---------------------------------------------------------------------------

def item_status_reason(li) -> str | None:
    """The comment/reason attached to whichever stage last acted on this item."""
    if li.status in ("hod_rejected", "hod_deferred", "hod_clarification_requested"):
        return li.hod_comment
    if li.status in ("qc_query_raised", "finance_rejected", "finance_deferred"):
        return li.finance_qc_comment
    if li.status in ("cfo_rejected", "deferred_by_cfo", "cfo_clarification_requested"):
        return li.cfo_reason
    if li.status in ("ceo_rejected", "ceo_deferred", "ceo_clarification_requested"):
        return li.ceo_reason
    return None


def flagged_items_for_notification(line_items) -> list[dict]:
    """Every item currently rejected, deferred, or awaiting clarification, with its reason."""
    flagged = []
    for li in line_items:
        if li.status in REJECTED_STATUSES or li.status in DEFERRED_STATUSES or li.status in CLARIFICATION_STATUSES:
            flagged.append({
                "vendor": li.vendor_name,
                "status": li.status,
                "reason": item_status_reason(li) or "No reason recorded.",
            })
    return flagged


def resolve_cfo_deferred_budget(submission, line_items, db: Session, approved: bool) -> None:
    for li in line_items:
        if not li.cfo_deferred or not li.cfo_defer_to_month:
            continue
        amount = Decimal(str(li.equivalent_usd))
        adjust_category_budget(
            li.category, submission.cost_type, li.cfo_defer_to_month, submission.year, db,
            delta_deferred=-amount,
            delta_approved=amount if approved else Decimal("0"),
        )


def defer_budget_for_submission(submission, deferred_line_items, target_month: int, db: Session) -> None:
    """Move a reservation from the submission's original month to the CFO-selected target month."""
    for category, amount in category_usd_totals(deferred_line_items).items():
        adjust_category_budget(
            category, submission.cost_type, submission.month, submission.year, db,
            delta_approved=-amount,
        )
        adjust_category_budget(
            category, submission.cost_type, target_month, submission.year, db,
            delta_deferred=amount,
        )


def check_category_budgets(
    cost_type: str,
    month: int,
    year: int,
    category_usd: dict[str, Decimal],
    db: Session,
) -> tuple[bool, list[dict]]:
    """
    Checks each category present in a submission against its own budget row.
    Returns (any_over_limit, details) — details lists only the categories that
    are over. A category with no budget row configured is skipped (warn-only
    policy, same as before).
    """
    any_over = False
    details: list[dict] = []
    for category, requested in category_usd.items():
        budget = (
            db.query(CategoryBudget)
            .filter(
                CategoryBudget.category == category,
                CategoryBudget.cost_type == cost_type,
                CategoryBudget.month == month,
                CategoryBudget.year == year,
            )
            .first()
        )
        if not budget or not budget.monthly_allocation_usd:
            continue
        allocation = Decimal(str(budget.monthly_allocation_usd))
        approved = Decimal(str(budget.approved_mtd))
        deferred = Decimal(str(budget.deferred_approved))
        remaining = allocation - approved - deferred
        overage = requested - remaining
        if overage > 0:
            any_over = True
            details.append({
                "category": category,
                "requested": requested,
                "remaining_before": remaining,
                "overage": overage,
            })
    return any_over, details


# ---------------------------------------------------------------------------
# Month name helper
# ---------------------------------------------------------------------------

def make_month_name(month: int, year: int) -> str:
    """Return abbreviated month + 2-digit year, e.g. 'Jan-26'."""
    abbrev = MONTH_NAMES[month][:3]
    return f"{abbrev}-{str(year)[-2:]}"


# ---------------------------------------------------------------------------
# Create submission
# ---------------------------------------------------------------------------

def create_submission(
    data: SubmissionIn,
    creator: User,
    db: Session,
) -> Submission:
    """
    Validates exchange rates, computes USD amounts, checks budget,
    persists Submission + LineItems + AuditLog.
    Raises ValueError on rate-fetch failure.
    """
    # Compute USD for every line item first (validates all rates exist)
    line_item_data: list[dict] = []
    total_usd = Decimal("0")
    category_usd: dict[str, Decimal] = {}

    for item in data.line_items:
        eq_usd, rate_used = convert_to_usd(item.original_amount, item.currency, db)
        total_usd += eq_usd
        category_usd[item.category] = category_usd.get(item.category, Decimal("0")) + eq_usd
        line_item_data.append({
            "item": item,
            "equivalent_usd": eq_usd,
            "exchange_rate_used": rate_used,
        })

    # Budget check — informational flag only; the actual reservation against the
    # category budget happens at HOD approval (see reserve_budget_for_submission).
    over_limit, overage_details = check_category_budgets(
        data.cost_type, data.month, data.year, category_usd, db
    )

    # Generate human-readable ID
    submission_id = generate_submission_id(db, data.year)
    month_name = make_month_name(data.month, data.year)

    is_urgent = isinstance(data, UrgentSubmissionIn)
    submission = Submission(
        submission_id=submission_id,
        department=data.department,
        month=data.month,
        month_name=month_name,
        year=data.year,
        cost_type=data.cost_type,
        supporting_justification=data.supporting_justification,
        status="pending_hod",
        request_type="urgent" if is_urgent else "standard",
        budget_over_limit_flag=over_limit,
        created_by=creator.id,
        urgency_category=data.urgency_category if is_urgent else None,
        urgency_reason=data.urgency_reason if is_urgent else None,
        requested_payment_date=data.requested_payment_date if is_urgent else None,
        finance_authoriser=data.finance_authoriser if is_urgent else None,
    )
    db.add(submission)
    db.flush()  # get submission.id

    for entry in line_item_data:
        item: LineItemIn = entry["item"]
        db.add(LineItem(
            submission_id=submission.id,
            vendor_name=item.vendor_name,
            invoice_no=item.invoice_no,
            po_number=item.po_number or None,
            description=item.description,
            items_products=item.items_products or None,
            category=item.category,
            account_code=item.account_code,
            billing_period_start=item.billing_period_start,
            billing_period_end=item.billing_period_end,
            payment_tracking_code=item.payment_tracking_code or None,
            frequency=item.frequency,
            status_remarks=item.status_remarks or None,
            currency=item.currency,
            original_amount=float(item.original_amount),
            equivalent_usd=float(entry["equivalent_usd"]),
            exchange_rate_used=float(entry["exchange_rate_used"]),
            is_arrear=item.is_arrear,
            arrear_type=item.arrear_type if item.is_arrear else None,
            cfo_deferred=False,
            status="pending_hod",
        ))

    overage_note = ""
    if over_limit:
        parts = [f"{d['category']} over by USD {d['overage']:,.2f}" for d in overage_details]
        overage_note = f" Budget over-limit — {'; '.join(parts)}."

    db.add(AuditLog(
        submission_id=submission.id,
        action="submission_created",
        outcome="pending_hod",
        performed_by=creator.id,
        amount_usd=float(total_usd),
        notes=f"{'URGENT — ' if is_urgent else ''}Submitted by {creator.display_name}. "
              f"{len(data.line_items)} line item(s). "
              f"Total: USD {total_usd:,.2f}."
              + overage_note
              + (f" Urgency: {data.urgency_category}. Requested payment: {data.requested_payment_date}." if is_urgent else ""),
    ))

    db.commit()
    db.refresh(submission)
    return submission
