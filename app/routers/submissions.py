"""
Submission routes:
  GET  /submissions/new                 — originator submission form
  POST /submissions/new                 — create submission
  GET  /submissions/line-items/add      — HTMX add line-item row
  GET  /submissions/mine                — originator's own submissions
  GET  /submissions/{id}/confirmation   — post-submit success page
  GET  /submissions/{id}                — detail view
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.constants import (
    ARREAR_TYPES,
    CASH_CALL_CATEGORIES,
    CURRENCIES,
    DEPARTMENT_GROUPS,
    PAYMENT_FREQUENCIES,
    SUBMISSION_STATUSES,
    URGENCY_CATEGORIES,
)
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.submission import Submission
from app.models.user import User
from app.schemas.submission import LineItemIn, SubmissionIn, UrgentSubmissionIn
from app.models.line_item import LineItem
from app.models.audit_log import AuditLog
from app.services.submission_service import create_submission, convert_to_usd

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/submissions", tags=["submissions"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _templates(request: Request):
    from app.main import templates
    return templates


def _flash(request: Request, message: str, category: str = "error") -> None:
    request.session.setdefault("flash_messages", []).append(
        {"message": message, "category": category}
    )


def _get_template_ctx(request: Request, **extra) -> dict[str, Any]:
    return {"request": request, **extra}


def _parse_line_items_from_form(form: dict) -> list[dict]:
    """
    Form fields are named vendor_name_0, vendor_name_1, … etc.
    Collect all present indices and build a list of raw dicts.
    """
    indices: list[int] = sorted(
        int(k.split("_")[-1])
        for k in form
        if k.startswith("vendor_name_") and k.split("_")[-1].isdigit()
    )
    items = []
    for i in indices:
        items.append({
            "vendor_name": form.get(f"vendor_name_{i}", ""),
            "invoice_no": form.get(f"invoice_no_{i}", ""),
            "po_number": form.get(f"po_number_{i}") or None,
            "description": form.get(f"description_{i}", ""),
            "items_products": form.get(f"items_products_{i}") or None,
            "category": form.get(f"category_{i}", ""),
            "account_code": form.get(f"account_code_{i}", ""),
            "billing_period_start": form.get(f"billing_period_start_{i}", ""),
            "billing_period_end": form.get(f"billing_period_end_{i}", ""),
            "payment_tracking_code": form.get(f"payment_tracking_code_{i}") or None,
            "frequency": form.get(f"frequency_{i}", ""),
            "status_remarks": form.get(f"status_remarks_{i}") or None,
            "currency": form.get(f"currency_{i}", ""),
            "original_amount": form.get(f"original_amount_{i}", "0"),
            "is_arrear": form.get(f"is_arrear_{i}") == "on",
            "arrear_type": form.get(f"arrear_type_{i}") or None,
        })
    return items


# ---------------------------------------------------------------------------
# HTMX: add line-item row
# ---------------------------------------------------------------------------

@router.get("/line-items/add", response_class=HTMLResponse)
async def add_line_item_row(
    request: Request,
    next_line_idx: int = 0,
    current_user: User = Depends(require_role("originator")),
):
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "submissions/_line_item_row.html",
        _get_template_ctx(
            request,
            idx=next_line_idx,
            categories=CASH_CALL_CATEGORIES,
            currencies=CURRENCIES,
            frequencies=PAYMENT_FREQUENCIES,
            arrear_types=ARREAR_TYPES,
            row={},
        ),
    )


# ---------------------------------------------------------------------------
# New submission form
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse)
async def new_submission_form(
    request: Request,
    current_user: User = Depends(require_role("originator")),
):
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "submissions/new.html",
        _get_template_ctx(
            request,
            user=current_user,
            department_groups=DEPARTMENT_GROUPS,
            categories=CASH_CALL_CATEGORIES,
            currencies=CURRENCIES,
            frequencies=PAYMENT_FREQUENCIES,
            arrear_types=ARREAR_TYPES,
            errors=None,
            form_data={},
            line_item_rows=[{}],  # start with one empty row
        ),
    )


@router.post("/new", response_class=HTMLResponse)
async def create_submission_route(
    request: Request,
    current_user: User = Depends(require_role("originator")),
    db: Session = Depends(get_db),
):
    form = dict(await request.form())
    raw_items = _parse_line_items_from_form(form)

    # Build payload dict for Pydantic
    payload = {
        "department": form.get("department", ""),
        "month": form.get("month", ""),
        "year": form.get("year", ""),
        "cost_type": form.get("cost_type", ""),
        "supporting_justification": form.get("supporting_justification", ""),
        "line_items": raw_items,
    }

    errors: list[str] = []
    submission_in: SubmissionIn | None = None
    try:
        submission_in = SubmissionIn(**payload)
    except ValidationError as exc:
        for e in exc.errors():
            loc = " → ".join(str(x) for x in e["loc"])
            errors.append(f"{loc}: {e['msg']}")
    except Exception as exc:
        errors.append(str(exc))

    tmpl = _templates(request)

    if errors or submission_in is None:
        return tmpl.TemplateResponse(
            "submissions/new.html",
            _get_template_ctx(
                request,
                user=current_user,
                department_groups=DEPARTMENT_GROUPS,
                categories=CASH_CALL_CATEGORIES,
                currencies=CURRENCIES,
                frequencies=PAYMENT_FREQUENCIES,
                arrear_types=ARREAR_TYPES,
                errors=errors,
                form_data=form,
                line_item_rows=raw_items,
            ),
            status_code=422,
        )

    try:
        submission = create_submission(submission_in, current_user, db)
    except ValueError as exc:
        errors.append(str(exc))
        return tmpl.TemplateResponse(
            "submissions/new.html",
            _get_template_ctx(
                request,
                user=current_user,
                department_groups=DEPARTMENT_GROUPS,
                categories=CASH_CALL_CATEGORIES,
                currencies=CURRENCIES,
                frequencies=PAYMENT_FREQUENCIES,
                arrear_types=ARREAR_TYPES,
                errors=errors,
                form_data=form,
                line_item_rows=raw_items,
            ),
            status_code=422,
        )

    return RedirectResponse(
        url=f"/submissions/{submission.submission_id}/confirmation",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Urgent submission form
# ---------------------------------------------------------------------------

@router.get("/urgent/new", response_class=HTMLResponse)
async def new_urgent_form(
    request: Request,
    current_user: User = Depends(require_role("originator")),
):
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "submissions/urgent_new.html",
        _get_template_ctx(
            request,
            user=current_user,
            department_groups=DEPARTMENT_GROUPS,
            categories=CASH_CALL_CATEGORIES,
            currencies=CURRENCIES,
            frequencies=PAYMENT_FREQUENCIES,
            arrear_types=ARREAR_TYPES,
            urgency_categories=URGENCY_CATEGORIES,
            errors=None,
            form_data={},
            line_item_rows=[{}],
        ),
    )


@router.post("/urgent/new", response_class=HTMLResponse)
async def create_urgent_submission(
    request: Request,
    current_user: User = Depends(require_role("originator")),
    db: Session = Depends(get_db),
):
    form = dict(await request.form())
    raw_items = _parse_line_items_from_form(form)

    payload = {
        "department": form.get("department", ""),
        "month": form.get("month", ""),
        "year": form.get("year", ""),
        "cost_type": form.get("cost_type", ""),
        "supporting_justification": form.get("supporting_justification", ""),
        "urgency_category": form.get("urgency_category", ""),
        "urgency_reason": form.get("urgency_reason", ""),
        "requested_payment_date": form.get("requested_payment_date", ""),
        "finance_authoriser": form.get("finance_authoriser", ""),
        "line_items": raw_items,
    }

    errors: list[str] = []
    submission_in: UrgentSubmissionIn | None = None
    try:
        submission_in = UrgentSubmissionIn(**payload)
    except ValidationError as exc:
        for e in exc.errors():
            loc = " → ".join(str(x) for x in e["loc"])
            errors.append(f"{loc}: {e['msg']}")
    except Exception as exc:
        errors.append(str(exc))

    tmpl = _templates(request)

    if errors or submission_in is None:
        return tmpl.TemplateResponse(
            "submissions/urgent_new.html",
            _get_template_ctx(
                request,
                user=current_user,
                department_groups=DEPARTMENT_GROUPS,
                categories=CASH_CALL_CATEGORIES,
                currencies=CURRENCIES,
                frequencies=PAYMENT_FREQUENCIES,
                arrear_types=ARREAR_TYPES,
                urgency_categories=URGENCY_CATEGORIES,
                errors=errors,
                form_data=form,
                line_item_rows=raw_items,
            ),
            status_code=422,
        )

    try:
        submission = create_submission(submission_in, current_user, db)
    except ValueError as exc:
        errors.append(str(exc))
        return tmpl.TemplateResponse(
            "submissions/urgent_new.html",
            _get_template_ctx(
                request,
                user=current_user,
                department_groups=DEPARTMENT_GROUPS,
                categories=CASH_CALL_CATEGORIES,
                currencies=CURRENCIES,
                frequencies=PAYMENT_FREQUENCIES,
                arrear_types=ARREAR_TYPES,
                urgency_categories=URGENCY_CATEGORIES,
                errors=errors,
                form_data=form,
                line_item_rows=raw_items,
            ),
            status_code=422,
        )

    return RedirectResponse(
        url=f"/submissions/{submission.submission_id}/confirmation",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# My submissions list
# ---------------------------------------------------------------------------

@router.get("/mine", response_class=HTMLResponse)
async def my_submissions(
    request: Request,
    current_user: User = Depends(require_role("originator")),
    db: Session = Depends(get_db),
):
    submissions = (
        db.query(Submission)
        .filter(Submission.created_by == current_user.id)
        .order_by(Submission.created_at.desc())
        .all()
    )
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "submissions/mine.html",
        _get_template_ctx(request, user=current_user, submissions=submissions),
    )


# ---------------------------------------------------------------------------
# Submission detail
# ---------------------------------------------------------------------------

@router.get("/{submission_id}/confirmation", response_class=HTMLResponse)
async def submission_confirmation(
    request: Request,
    submission_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    submission = (
        db.query(Submission)
        .filter(Submission.submission_id == submission_id)
        .first()
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    if submission.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "submissions/confirmation.html",
        _get_template_ctx(request, user=current_user, submission=submission),
    )


@router.get("/{submission_id}", response_class=HTMLResponse)
async def submission_detail(
    request: Request,
    submission_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    submission = (
        db.query(Submission)
        .filter(Submission.submission_id == submission_id)
        .first()
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Access: originator who created it, or any approval-chain role
    allowed_roles = {"hod", "finance_reviewer", "cfo", "ceo", "treasury", "it_admin"}
    if current_user.role not in allowed_roles and submission.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "submissions/detail.html",
        _get_template_ctx(request, user=current_user, submission=submission),
    )


# ---------------------------------------------------------------------------
# Edit & resubmit (only for hod_returned submissions)
# ---------------------------------------------------------------------------

@router.get("/{submission_id}/edit", response_class=HTMLResponse)
async def edit_submission_form(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("originator")),
    db: Session = Depends(get_db),
):
    sub = db.query(Submission).filter(Submission.submission_id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if sub.status != "hod_returned":
        raise HTTPException(status_code=409, detail="Only returned submissions can be edited")

    existing_rows = [
        {
            "vendor_name": li.vendor_name,
            "invoice_no": li.invoice_no,
            "po_number": li.po_number or "",
            "description": li.description,
            "items_products": li.items_products or "",
            "category": li.category,
            "account_code": li.account_code,
            "billing_period_start": str(li.billing_period_start),
            "billing_period_end": str(li.billing_period_end),
            "payment_tracking_code": li.payment_tracking_code or "",
            "frequency": li.frequency,
            "status_remarks": li.status_remarks or "",
            "currency": li.currency,
            "original_amount": str(li.original_amount),
            "is_arrear": li.is_arrear,
            "arrear_type": li.arrear_type or "",
        }
        for li in sub.line_items
    ]
    form_data = {
        "department": sub.department,
        "month": str(sub.month),
        "year": str(sub.year),
        "cost_type": sub.cost_type,
        "supporting_justification": sub.supporting_justification,
    }
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "submissions/new.html",
        _get_template_ctx(
            request,
            user=current_user,
            department_groups=DEPARTMENT_GROUPS,
            categories=CASH_CALL_CATEGORIES,
            currencies=CURRENCIES,
            frequencies=PAYMENT_FREQUENCIES,
            arrear_types=ARREAR_TYPES,
            errors=None,
            form_data=form_data,
            line_item_rows=existing_rows,
            editing_submission=sub,
            hod_comment=sub.hod_comment,
        ),
    )


@router.post("/{submission_id}/edit", response_class=HTMLResponse)
async def resubmit_submission(
    request: Request,
    submission_id: str,
    current_user: User = Depends(require_role("originator")),
    db: Session = Depends(get_db),
):
    sub = db.query(Submission).filter(Submission.submission_id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if sub.status != "hod_returned":
        raise HTTPException(status_code=409, detail="Only returned submissions can be resubmitted")

    form = dict(await request.form())
    raw_items = _parse_line_items_from_form(form)

    payload = {
        "department": form.get("department", sub.department),
        "month": form.get("month", str(sub.month)),
        "year": form.get("year", str(sub.year)),
        "cost_type": form.get("cost_type", sub.cost_type),
        "supporting_justification": form.get("supporting_justification", ""),
        "line_items": raw_items,
    }

    errors: list[str] = []
    submission_in: SubmissionIn | None = None
    try:
        submission_in = SubmissionIn(**payload)
    except ValidationError as exc:
        for e in exc.errors():
            loc = " → ".join(str(x) for x in e["loc"])
            errors.append(f"{loc}: {e['msg']}")

    tmpl = _templates(request)
    if errors or submission_in is None:
        return tmpl.TemplateResponse(
            "submissions/new.html",
            _get_template_ctx(
                request,
                user=current_user,
                department_groups=DEPARTMENT_GROUPS,
                categories=CASH_CALL_CATEGORIES,
                currencies=CURRENCIES,
                frequencies=PAYMENT_FREQUENCIES,
                arrear_types=ARREAR_TYPES,
                errors=errors,
                form_data=form,
                line_item_rows=raw_items,
                editing_submission=sub,
                hod_comment=sub.hod_comment,
            ),
            status_code=422,
        )

    # Delete old line items and replace with new ones
    for li in sub.line_items:
        db.delete(li)
    db.flush()

    from datetime import datetime, timezone
    from decimal import Decimal
    now = datetime.now(timezone.utc)

    sub.department = submission_in.department
    sub.month = submission_in.month
    sub.year = submission_in.year
    sub.cost_type = submission_in.cost_type
    sub.supporting_justification = submission_in.supporting_justification
    sub.status = "pending_hod"
    sub.hod_decision = None
    sub.hod_comment = None
    sub.hod_decided_at = None
    sub.hod_decided_by = None

    for item in submission_in.line_items:
        equiv_usd, rate_used = convert_to_usd(item.original_amount, item.currency, db)
        db.add(LineItem(
            submission_id=sub.id,
            vendor_name=item.vendor_name,
            invoice_no=item.invoice_no,
            po_number=item.po_number,
            description=item.description,
            items_products=item.items_products,
            category=item.category,
            account_code=item.account_code,
            billing_period_start=item.billing_period_start,
            billing_period_end=item.billing_period_end,
            payment_tracking_code=item.payment_tracking_code,
            frequency=item.frequency,
            status_remarks=item.status_remarks,
            currency=item.currency,
            original_amount=item.original_amount,
            equivalent_usd=equiv_usd,
            exchange_rate_used=rate_used,
            is_arrear=item.is_arrear,
            arrear_type=item.arrear_type,
        ))

    db.add(AuditLog(
        submission_id=sub.id,
        action="resubmitted",
        outcome="pending_hod",
        performed_by=current_user.id,
        notes="Originator resubmitted after HOD return.",
    ))
    db.commit()

    return RedirectResponse(
        url=f"/submissions/{submission_id}/confirmation",
        status_code=303,
    )
