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

from app.constants import MONTH_NAMES
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
# Budget check
# ---------------------------------------------------------------------------

def check_budget(
    department: str,
    month: int,
    year: int,
    total_requested_usd: Decimal,
    db: Session,
) -> tuple[bool, Decimal]:
    """
    Returns (over_limit: bool, overage_amount: Decimal).
    over_limit=False if no budget row is configured (warn-only policy).
    """
    budget = (
        db.query(CategoryBudget)
        .filter(
            CategoryBudget.department == department,
            CategoryBudget.month == month,
            CategoryBudget.year == year,
        )
        .first()
    )
    if not budget or not budget.monthly_allocation_usd:
        return False, Decimal("0")

    allocation = Decimal(str(budget.monthly_allocation_usd))
    approved = Decimal(str(budget.approved_mtd))
    deferred = Decimal(str(budget.deferred_approved))
    remaining = allocation - approved - deferred
    overage = total_requested_usd - remaining
    return overage > 0, max(overage, Decimal("0"))


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

    for item in data.line_items:
        eq_usd, rate_used = convert_to_usd(item.original_amount, item.currency, db)
        total_usd += eq_usd
        line_item_data.append({
            "item": item,
            "equivalent_usd": eq_usd,
            "exchange_rate_used": rate_used,
        })

    # Budget check
    over_limit, overage = check_budget(
        data.department, data.month, data.year, total_usd, db
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
        ))

    db.add(AuditLog(
        submission_id=submission.id,
        action="submission_created",
        outcome="pending_hod",
        performed_by=creator.id,
        amount_usd=float(total_usd),
        notes=f"{'URGENT — ' if is_urgent else ''}Submitted by {creator.display_name}. "
              f"{len(data.line_items)} line item(s). "
              f"Total: USD {total_usd:,.2f}."
              + (f" Budget over-limit by USD {overage:,.2f}." if over_limit else "")
              + (f" Urgency: {data.urgency_category}. Requested payment: {data.requested_payment_date}." if is_urgent else ""),
    ))

    db.commit()
    db.refresh(submission)
    return submission
