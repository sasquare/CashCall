"""
Submission routes:
  GET  /submissions/new                 — originator submission form
  POST /submissions/new                 — create submission
  GET  /submissions/line-items/add      — HTMX add line-item row
  GET  /submissions/batch-upload        — upload line items (xlsx) into one submission
  GET  /submissions/bulk-import         — upload multiple submissions at once (xlsx)
  GET  /submissions/mine                — originator's own submissions
  GET  /submissions/{id}/confirmation   — post-submit success page
  GET  /submissions/{id}                — detail view
"""

from __future__ import annotations

import io
import logging
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
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
from app.services.batch_import_service import (
    BULK_IMPORT_COLUMNS,
    BULK_IMPORT_EXAMPLE,
    LINE_ITEM_COLUMNS,
    LINE_ITEM_EXAMPLE,
    build_template_workbook,
    coerce_line_item_row,
    parse_uploaded_workbook,
)

logger = logging.getLogger(__name__)

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

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
# Batch upload — many line items into ONE submission (xlsx)
# ---------------------------------------------------------------------------

def _format_line_item_validation_errors(exc: ValidationError, row_offset: int = 2) -> list[str]:
    formatted: list[str] = []
    for e in exc.errors():
        loc = e["loc"]
        if len(loc) >= 2 and loc[0] == "line_items" and isinstance(loc[1], int):
            field = " → ".join(str(x) for x in loc[2:])
            formatted.append(f"Row {loc[1] + row_offset} ({field}): {e['msg']}")
        else:
            formatted.append(f"{' → '.join(str(x) for x in loc)}: {e['msg']}")
    return formatted


@router.get("/batch-upload", response_class=HTMLResponse)
async def batch_upload_form(
    request: Request,
    current_user: User = Depends(require_role("originator")),
):
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "submissions/batch_upload.html",
        _get_template_ctx(
            request,
            user=current_user,
            department_groups=DEPARTMENT_GROUPS,
            urgency_categories=URGENCY_CATEGORIES,
            errors=None,
            row_errors=None,
            form_data={},
        ),
    )


@router.get("/batch-upload/template")
async def batch_upload_template(
    current_user: User = Depends(require_role("originator")),
):
    content = build_template_workbook(LINE_ITEM_COLUMNS, example_row=LINE_ITEM_EXAMPLE)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=cashcall_line_items_template.xlsx"},
    )


@router.post("/batch-upload", response_class=HTMLResponse)
async def batch_upload_submit(
    request: Request,
    current_user: User = Depends(require_role("originator")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    upload = form.get("file")
    tmpl = _templates(request)
    base_ctx = dict(
        user=current_user,
        department_groups=DEPARTMENT_GROUPS,
        urgency_categories=URGENCY_CATEGORIES,
        form_data={k: v for k, v in form.items() if k != "file"},
    )

    if upload is None or not getattr(upload, "filename", ""):
        return tmpl.TemplateResponse(
            "submissions/batch_upload.html",
            _get_template_ctx(request, errors=["Please choose an .xlsx file to upload."], row_errors=None, **base_ctx),
            status_code=422,
        )

    file_bytes = await upload.read()
    raw_rows, parse_errors = parse_uploaded_workbook(file_bytes, LINE_ITEM_COLUMNS)
    if parse_errors:
        return tmpl.TemplateResponse(
            "submissions/batch_upload.html",
            _get_template_ctx(request, errors=parse_errors, row_errors=None, **base_ctx),
            status_code=422,
        )
    if not raw_rows:
        return tmpl.TemplateResponse(
            "submissions/batch_upload.html",
            _get_template_ctx(request, errors=["No data rows found in the uploaded file."], row_errors=None, **base_ctx),
            status_code=422,
        )

    line_items: list[dict] = []
    row_errors: list[str] = []
    for i, raw in enumerate(raw_rows):
        try:
            line_items.append(coerce_line_item_row(raw))
        except ValueError as exc:
            row_errors.append(f"Row {i + 2}: {exc}")

    is_urgent = form.get("is_urgent") == "on"
    payload: dict[str, Any] = {
        "department": form.get("department", ""),
        "month": form.get("month", ""),
        "year": form.get("year", ""),
        "cost_type": form.get("cost_type", ""),
        "supporting_justification": form.get("supporting_justification", ""),
        "line_items": line_items,
    }
    if is_urgent:
        payload.update({
            "urgency_category": form.get("urgency_category", ""),
            "urgency_reason": form.get("urgency_reason", ""),
            "requested_payment_date": form.get("requested_payment_date", ""),
            "finance_authoriser": form.get("finance_authoriser", ""),
        })

    submission_in: SubmissionIn | UrgentSubmissionIn | None = None
    if not row_errors:
        try:
            submission_in = UrgentSubmissionIn(**payload) if is_urgent else SubmissionIn(**payload)
        except ValidationError as exc:
            row_errors.extend(_format_line_item_validation_errors(exc))

    if row_errors or submission_in is None:
        return tmpl.TemplateResponse(
            "submissions/batch_upload.html",
            _get_template_ctx(request, errors=None, row_errors=row_errors, **base_ctx),
            status_code=422,
        )

    try:
        submission = create_submission(submission_in, current_user, db)
    except ValueError as exc:
        return tmpl.TemplateResponse(
            "submissions/batch_upload.html",
            _get_template_ctx(request, errors=[str(exc)], row_errors=None, **base_ctx),
            status_code=422,
        )

    return RedirectResponse(url=f"/submissions/{submission.submission_id}/confirmation", status_code=303)


# ---------------------------------------------------------------------------
# Bulk import — MULTIPLE submissions at once, grouped by "Batch Ref" (xlsx)
# ---------------------------------------------------------------------------

@router.get("/bulk-import", response_class=HTMLResponse)
async def bulk_import_form(
    request: Request,
    current_user: User = Depends(require_role("originator")),
):
    tmpl = _templates(request)
    return tmpl.TemplateResponse(
        "submissions/bulk_import.html",
        _get_template_ctx(request, user=current_user, errors=None),
    )


@router.get("/bulk-import/template")
async def bulk_import_template(
    current_user: User = Depends(require_role("originator")),
):
    content = build_template_workbook(BULK_IMPORT_COLUMNS, example_row=BULK_IMPORT_EXAMPLE)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=cashcall_bulk_import_template.xlsx"},
    )


@router.post("/bulk-import", response_class=HTMLResponse)
async def bulk_import_submit(
    request: Request,
    current_user: User = Depends(require_role("originator")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    upload = form.get("file")
    tmpl = _templates(request)

    if upload is None or not getattr(upload, "filename", ""):
        return tmpl.TemplateResponse(
            "submissions/bulk_import.html",
            _get_template_ctx(request, user=current_user, errors=["Please choose an .xlsx file to upload."]),
            status_code=422,
        )

    file_bytes = await upload.read()
    raw_rows, parse_errors = parse_uploaded_workbook(file_bytes, BULK_IMPORT_COLUMNS)
    if parse_errors:
        return tmpl.TemplateResponse(
            "submissions/bulk_import.html",
            _get_template_ctx(request, user=current_user, errors=parse_errors),
            status_code=422,
        )
    if not raw_rows:
        return tmpl.TemplateResponse(
            "submissions/bulk_import.html",
            _get_template_ctx(request, user=current_user, errors=["No data rows found in the uploaded file."]),
            status_code=422,
        )

    # Group rows by Batch Ref, preserving first-seen order.
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for i, raw in enumerate(raw_rows):
        ref = str(raw.get("batch_ref") or "").strip()
        if not ref:
            ref = f"(ungrouped row {i + 2})"
        if ref not in groups:
            groups[ref] = []
            order.append(ref)
        groups[ref].append({**raw, "_excel_row": i + 2})

    created: list[str] = []
    failures: list[dict[str, str]] = []

    for ref in order:
        group_rows = groups[ref]
        first = group_rows[0]

        mismatch = None
        for key in ("department", "month", "year", "cost_type"):
            values = {str(r.get(key)).strip() for r in group_rows}
            if len(values) > 1:
                mismatch = key
                break
        if mismatch:
            failures.append({
                "batch_ref": ref,
                "error": f'Rows disagree on "{mismatch}" — all rows sharing a Batch Ref must have the same {mismatch}.',
            })
            continue

        line_items: list[dict] = []
        row_errors: list[str] = []
        for r in group_rows:
            try:
                line_items.append(coerce_line_item_row(r))
            except ValueError as exc:
                row_errors.append(f"Row {r['_excel_row']}: {exc}")

        payload = {
            "department": str(first.get("department") or "").strip(),
            "month": str(first.get("month") or "").strip(),
            "year": str(first.get("year") or "").strip(),
            "cost_type": str(first.get("cost_type") or "").strip().lower(),
            "supporting_justification": str(first.get("supporting_justification") or "").strip(),
            "line_items": line_items,
        }

        submission_in: SubmissionIn | None = None
        if not row_errors:
            try:
                submission_in = SubmissionIn(**payload)
            except ValidationError as exc:
                for e in exc.errors():
                    loc = e["loc"]
                    if len(loc) >= 2 and loc[0] == "line_items" and isinstance(loc[1], int):
                        excel_row = group_rows[loc[1]]["_excel_row"]
                        field = " → ".join(str(x) for x in loc[2:])
                        row_errors.append(f"Row {excel_row} ({field}): {e['msg']}")
                    else:
                        row_errors.append(f"{' → '.join(str(x) for x in loc)}: {e['msg']}")

        if row_errors or submission_in is None:
            failures.append({"batch_ref": ref, "error": "; ".join(row_errors)})
            continue

        try:
            submission = create_submission(submission_in, current_user, db)
            created.append(submission.submission_id)
        except ValueError as exc:
            failures.append({"batch_ref": ref, "error": str(exc)})

    return tmpl.TemplateResponse(
        "submissions/bulk_import_result.html",
        _get_template_ctx(request, user=current_user, created=created, failures=failures),
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
