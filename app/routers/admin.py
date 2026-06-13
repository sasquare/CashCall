"""
IT Admin panel:
  GET  /admin                       — overview dashboard
  GET  /admin/users                 — user list
  GET  /admin/users/new             — create user form
  POST /admin/users/new             — create user
  GET  /admin/users/{id}/edit       — edit user form
  POST /admin/users/{id}/edit       — update user
  POST /admin/users/{id}/toggle     — activate / deactivate

  GET  /admin/rates                 — exchange rate list
  POST /admin/rates                 — add new rate

  GET  /admin/budgets               — budget list (current month)
  POST /admin/budgets               — upsert budget row

  GET  /admin/audit                 — paginated audit log

  GET  /admin/reports               — reporting dashboard
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import bcrypt
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.constants import (
    ALL_DEPARTMENTS,
    CURRENCIES,
    DEPARTMENT_GROUPS,
    MONTH_NAMES,
    USER_ROLES,
)
from app.database import get_db
from app.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.category_budget import CategoryBudget
from app.models.exchange_rate import ExchangeRate
from app.models.submission import Submission
from app.models.system_audit_log import SystemAuditLog
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])

PAGE_SIZE = 30


def _templates(request: Request):
    from app.main import templates
    return templates


def _ctx(request: Request, **kw):
    return {"request": request, **kw}


def _hash(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


# ---------------------------------------------------------------------------
# Overview dashboard
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def admin_home(
    request: Request,
    current_user: User = Depends(require_role("it_admin")),
    db: Session = Depends(get_db),
):
    total_users = db.query(func.count(User.id)).scalar()
    active_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar()  # noqa: E712
    total_submissions = db.query(func.count(Submission.id)).scalar()
    pending_count = db.query(func.count(Submission.id)).filter(
        Submission.status.in_(["pending_hod", "pending_finance_qc", "pending_cfo", "pending_ceo", "pending_treasury_payment"])
    ).scalar()
    recent_logs = (
        db.query(AuditLog)
        .order_by(AuditLog.performed_at.desc())
        .limit(10)
        .all()
    )
    tmpl = _templates(request)
    return tmpl.TemplateResponse("admin/home.html", _ctx(
        request, user=current_user,
        total_users=total_users, active_users=active_users,
        total_submissions=total_submissions, pending_count=pending_count,
        recent_logs=recent_logs,
    ))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@router.get("/users", response_class=HTMLResponse)
async def user_list(
    request: Request,
    current_user: User = Depends(require_role("it_admin")),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.role, User.display_name).all()
    tmpl = _templates(request)
    return tmpl.TemplateResponse("admin/users.html", _ctx(
        request, user=current_user, users=users, roles=USER_ROLES,
    ))


@router.get("/users/new", response_class=HTMLResponse)
async def new_user_form(
    request: Request,
    current_user: User = Depends(require_role("it_admin")),
):
    tmpl = _templates(request)
    return tmpl.TemplateResponse("admin/user_form.html", _ctx(
        request, user=current_user, editing=None,
        roles=USER_ROLES, department_groups=DEPARTMENT_GROUPS,
        errors=None, form_data={},
    ))


@router.post("/users/new", response_class=HTMLResponse)
async def create_user(
    request: Request,
    current_user: User = Depends(require_role("it_admin")),
    db: Session = Depends(get_db),
):
    form = dict(await request.form())
    errors = _validate_user_form(form, db, editing_id=None)
    tmpl = _templates(request)
    if errors:
        return tmpl.TemplateResponse("admin/user_form.html", _ctx(
            request, user=current_user, editing=None,
            roles=USER_ROLES, department_groups=DEPARTMENT_GROUPS,
            errors=errors, form_data=form,
        ), status_code=422)

    db.add(User(
        email=form["email"].strip().lower(),
        display_name=form["display_name"].strip(),
        role=form["role"],
        department=form.get("department") or None,
        is_active=True,
        alternate_email=form.get("alternate_email", "").strip() or None,
        hashed_password=_hash(form["password"]) if form.get("password") else None,
    ))
    db.commit()
    return RedirectResponse(url="/admin/users?created=1", status_code=303)


@router.get("/users/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_form(
    request: Request,
    user_id: int,
    current_user: User = Depends(require_role("it_admin")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    tmpl = _templates(request)
    return tmpl.TemplateResponse("admin/user_form.html", _ctx(
        request, user=current_user, editing=target,
        roles=USER_ROLES, department_groups=DEPARTMENT_GROUPS,
        errors=None, form_data={},
    ))


@router.post("/users/{user_id}/edit", response_class=HTMLResponse)
async def update_user(
    request: Request,
    user_id: int,
    current_user: User = Depends(require_role("it_admin")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    form = dict(await request.form())
    errors = _validate_user_form(form, db, editing_id=user_id)
    tmpl = _templates(request)
    if errors:
        return tmpl.TemplateResponse("admin/user_form.html", _ctx(
            request, user=current_user, editing=target,
            roles=USER_ROLES, department_groups=DEPARTMENT_GROUPS,
            errors=errors, form_data=form,
        ), status_code=422)

    target.email = form["email"].strip().lower()
    target.display_name = form["display_name"].strip()
    target.role = form["role"]
    target.department = form.get("department") or None
    target.alternate_email = form.get("alternate_email", "").strip() or None
    if form.get("password"):
        target.hashed_password = _hash(form["password"])
    db.commit()
    return RedirectResponse(url="/admin/users?updated=1", status_code=303)


@router.post("/users/{user_id}/toggle", response_class=HTMLResponse)
async def toggle_user(
    request: Request,
    user_id: int,
    current_user: User = Depends(require_role("it_admin")),
    db: Session = Depends(get_db),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account.")
    target.is_active = not target.is_active
    db.commit()
    return RedirectResponse(url="/admin/users?toggled=1", status_code=303)


def _validate_user_form(form: dict, db: Session, editing_id: int | None) -> list[str]:
    errors: list[str] = []
    email = form.get("email", "").strip().lower()
    if not email:
        errors.append("Email is required.")
    else:
        existing = db.query(User).filter(User.email == email).first()
        if existing and existing.id != editing_id:
            errors.append(f"Email {email} is already in use.")
    if not form.get("display_name", "").strip():
        errors.append("Display name is required.")
    if form.get("role") not in USER_ROLES:
        errors.append("Invalid role.")
    if editing_id is None and not form.get("password"):
        errors.append("Password is required for new users.")
    return errors


# ---------------------------------------------------------------------------
# Exchange rates
# ---------------------------------------------------------------------------

@router.get("/rates", response_class=HTMLResponse)
async def rates_list(
    request: Request,
    current_user: User = Depends(require_role("it_admin", "finance_reviewer", "cfo")),
    db: Session = Depends(get_db),
):
    rates = (
        db.query(ExchangeRate)
        .order_by(ExchangeRate.currency, ExchangeRate.effective_from.desc())
        .all()
    )
    # Current active rate per currency
    today = date.today()
    active: dict[str, ExchangeRate] = {}
    for r in rates:
        if r.effective_from <= today and r.currency not in active:
            active[r.currency] = r

    tmpl = _templates(request)
    return tmpl.TemplateResponse("admin/rates.html", _ctx(
        request, user=current_user,
        rates=rates, active=active, currencies=CURRENCIES,
        today=today,
    ))


@router.post("/rates", response_class=HTMLResponse)
async def add_rate(
    request: Request,
    current_user: User = Depends(require_role("it_admin", "finance_reviewer", "cfo")),
    db: Session = Depends(get_db),
):
    form = dict(await request.form())
    errors: list[str] = []
    currency = form.get("currency", "")
    if currency not in CURRENCIES:
        errors.append("Invalid currency.")
    try:
        rate_val = float(form.get("rate_to_usd", "0"))
        if rate_val <= 0:
            raise ValueError
    except (ValueError, TypeError):
        errors.append("Rate must be a positive number.")
    try:
        eff_from = date.fromisoformat(form.get("effective_from", ""))
    except ValueError:
        errors.append("Valid effective-from date is required.")
        eff_from = date.today()

    if errors:
        rates = db.query(ExchangeRate).order_by(ExchangeRate.currency, ExchangeRate.effective_from.desc()).all()
        today = date.today()
        active: dict[str, ExchangeRate] = {}
        for r in rates:
            if r.effective_from <= today and r.currency not in active:
                active[r.currency] = r
        tmpl = _templates(request)
        return _templates(request).TemplateResponse("admin/rates.html", _ctx(
            request, user=current_user,
            rates=rates, active=active, currencies=CURRENCIES,
            today=today, errors=errors, form_data=form,
        ), status_code=422)

    source = form.get("source", "").strip() or "Manual entry"

    # Expire the current active rate for this currency (set valid_until to yesterday)
    today = date.today()
    existing = db.query(ExchangeRate).filter(
        ExchangeRate.currency == currency,
        ExchangeRate.effective_from <= today,
        ExchangeRate.valid_until == None,  # noqa: E711
    ).order_by(ExchangeRate.effective_from.desc()).first()

    old_rate_str = None
    if existing:
        from datetime import timedelta
        existing.valid_until = eff_from - timedelta(days=1)
        old_rate_str = f"{existing.rate_to_usd} (from {existing.effective_from})"

    new_rate = ExchangeRate(
        currency=currency,
        rate_to_usd=rate_val,
        effective_from=eff_from,
        valid_until=None,
        updated_by=current_user.id,
        source=source,
    )
    db.add(new_rate)

    # Write system audit log entry
    db.add(SystemAuditLog(
        event_type="exchange_rate_updated",
        performed_by=current_user.id,
        old_value=old_rate_str,
        new_value=f"{rate_val} (from {eff_from})",
        notes=f"{currency} rate updated. Source: {source}",
    ))

    db.commit()
    return RedirectResponse(url="/admin/rates?added=1", status_code=303)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

@router.get("/budgets", response_class=HTMLResponse)
async def budgets_list(
    request: Request,
    current_user: User = Depends(require_role("it_admin", "finance_reviewer", "cfo")),
    db: Session = Depends(get_db),
):
    today = date.today()
    sel_month = int(request.query_params.get("month", today.month))
    sel_year = int(request.query_params.get("year", today.year))

    budgets = (
        db.query(CategoryBudget)
        .filter(CategoryBudget.month == sel_month, CategoryBudget.year == sel_year)
        .order_by(CategoryBudget.department)
        .all()
    )
    budget_map = {b.department: b for b in budgets}

    tmpl = _templates(request)
    return tmpl.TemplateResponse("admin/budgets.html", _ctx(
        request, user=current_user,
        budgets=budgets, budget_map=budget_map,
        all_departments=ALL_DEPARTMENTS,
        sel_month=sel_month, sel_year=sel_year,
        month_names=MONTH_NAMES,
        years=list(range(today.year - 1, today.year + 3)),
    ))


@router.post("/budgets", response_class=HTMLResponse)
async def upsert_budget(
    request: Request,
    current_user: User = Depends(require_role("it_admin", "finance_reviewer", "cfo")),
    db: Session = Depends(get_db),
):
    form = dict(await request.form())
    department = form.get("department", "").strip()
    if not department:
        raise HTTPException(status_code=422, detail="Department is required.")
    try:
        month = int(form["month"])
        year = int(form["year"])
        allocation_usd = float(form.get("monthly_allocation_usd", "0") or "0")
        allocation_ngn = float(form.get("monthly_allocation_ngn", "0") or "0")
        annual_usd = float(form.get("annual_allocation_usd", "0") or "0")
    except (ValueError, KeyError):
        raise HTTPException(status_code=422, detail="Invalid numeric values.")

    existing = (
        db.query(CategoryBudget)
        .filter(
            CategoryBudget.department == department,
            CategoryBudget.month == month,
            CategoryBudget.year == year,
        )
        .first()
    )
    if existing:
        existing.monthly_allocation_usd = allocation_usd
        existing.monthly_allocation_ngn = allocation_ngn
        existing.annual_allocation_usd = annual_usd
    else:
        db.add(CategoryBudget(
            department=department,
            month=month,
            year=year,
            monthly_allocation_usd=allocation_usd,
            monthly_allocation_ngn=allocation_ngn,
            annual_allocation_usd=annual_usd,
        ))
    db.commit()
    return RedirectResponse(
        url=f"/admin/budgets?month={month}&year={year}&saved=1",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@router.get("/audit", response_class=HTMLResponse)
async def audit_log(
    request: Request,
    current_user: User = Depends(require_role("it_admin", "finance_reviewer", "cfo")),
    db: Session = Depends(get_db),
):
    page = max(1, int(request.query_params.get("page", 1)))
    total = db.query(func.count(AuditLog.id)).scalar()
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, pages)

    logs = (
        db.query(AuditLog)
        .order_by(AuditLog.performed_at.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )

    system_logs = (
        db.query(SystemAuditLog)
        .order_by(SystemAuditLog.performed_at.desc())
        .limit(50)
        .all()
    )

    tmpl = _templates(request)
    return tmpl.TemplateResponse("admin/audit.html", _ctx(
        request, user=current_user,
        logs=logs, page=page, pages=pages, total=total,
        system_logs=system_logs,
    ))


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@router.get("/reports", response_class=HTMLResponse)
async def reports(
    request: Request,
    current_user: User = Depends(require_role("it_admin", "cfo", "ceo", "finance_reviewer")),
    db: Session = Depends(get_db),
):
    today = date.today()
    sel_month = int(request.query_params.get("month", today.month))
    sel_year = int(request.query_params.get("year", today.year))

    # Submissions this period
    period_subs = (
        db.query(Submission)
        .filter(Submission.month == sel_month, Submission.year == sel_year)
        .all()
    )

    # Status breakdown
    status_counts: dict[str, int] = {}
    for sub in period_subs:
        status_counts[sub.status] = status_counts.get(sub.status, 0) + 1

    # By department — total USD requested, status
    dept_totals: dict[str, dict] = {}
    for sub in period_subs:
        d = sub.department
        if d not in dept_totals:
            dept_totals[d] = {"count": 0, "total_usd": 0.0, "paid": 0.0, "pending": 0, "urgent": 0}
        dept_totals[d]["count"] += 1
        active_usd = float(sum(li.equivalent_usd for li in sub.line_items if not li.cfo_deferred))
        dept_totals[d]["total_usd"] += active_usd
        if sub.status == "paid":
            dept_totals[d]["paid"] += float(active_usd)
        elif sub.status in ("pending_hod", "pending_finance_qc", "qc_query_raised",
                            "pending_cfo", "pending_ceo", "pending_treasury_payment"):
            dept_totals[d]["pending"] += 1
        if sub.request_type == "urgent":
            dept_totals[d]["urgent"] += 1

    # Budget utilisation for this period
    budgets = (
        db.query(CategoryBudget)
        .filter(CategoryBudget.month == sel_month, CategoryBudget.year == sel_year)
        .all()
    )
    budget_map = {b.department: b for b in budgets}

    tmpl = _templates(request)
    return tmpl.TemplateResponse("admin/reports.html", _ctx(
        request, user=current_user,
        sel_month=sel_month, sel_year=sel_year,
        month_names=MONTH_NAMES,
        years=list(range(today.year - 1, today.year + 2)),
        total_subs=len(period_subs),
        status_counts=status_counts,
        dept_totals=dict(sorted(dept_totals.items())),
        budget_map=budget_map,
    ))
