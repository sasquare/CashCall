"""
Seed script for development.

Run from the project root:
    python scripts/seed.py

Creates:
- One user per role (7 total)
- One HOD + one Originator for a representative sample of 15 departments
- Exchange rates for all 5 currencies (effective today)
- Category budget rows for all seeded departments (current month + year)
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bcrypt
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import CategoryBudget, ExchangeRate, User


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

TODAY = date.today()
CURRENT_MONTH = TODAY.month
CURRENT_YEAR = TODAY.year


# ---------------------------------------------------------------------------
# Exchange rates (Finance-approved illustrative rates — update via admin panel)
# USD is the base: 1 USD = X units of foreign currency → rate_to_usd = 1/X
# We store "how many units of foreign currency equal 1 USD"
# so equivalent_usd = original_amount / rate_to_usd
# ---------------------------------------------------------------------------
EXCHANGE_RATES = [
    {"currency": "USD", "rate_to_usd": 1.0,      "source": "Base currency"},
    {"currency": "NGN", "rate_to_usd": 1600.00,   "source": "CBN Official Rate"},
    {"currency": "EUR", "rate_to_usd": 0.92,       "source": "ECB Reference Rate"},
    {"currency": "GBP", "rate_to_usd": 0.79,       "source": "Bank of England"},
    {"currency": "INR", "rate_to_usd": 83.50,      "source": "RBI Reference Rate"},
]

# ---------------------------------------------------------------------------
# One user per role (global — not dept-specific)
# ---------------------------------------------------------------------------
ROLE_USERS = [
    {
        "email": "finance.reviewer@dangote.com",
        "display_name": "Finance Reviewer",
        "role": "finance_reviewer",
        "department": None,
        "password": "Finance@123",
    },
    {
        "email": "cfo@dangote.com",
        "display_name": "Chief Financial Officer",
        "role": "cfo",
        "department": None,
        "password": "CFO@12345",
    },
    {
        "email": "ceo@dangote.com",
        "display_name": "Chief Executive Officer",
        "role": "ceo",
        "department": None,
        "password": "CEO@12345",
    },
    {
        "email": "treasury@dangote.com",
        "display_name": "Treasury Officer",
        "role": "treasury",
        "department": None,
        "password": "Treasury@123",
    },
    {
        "email": "it.admin@dangote.com",
        "display_name": "IT Administrator",
        "role": "it_admin",
        "department": None,
        "password": "ITAdmin@123",
    },
]

# ---------------------------------------------------------------------------
# Representative departments — one HOD + one Originator each.
# Full department list is in app/constants.py; add more via the admin panel.
# ---------------------------------------------------------------------------
SAMPLE_DEPARTMENTS = [
    ("DPRP-Finance & Accounts Department",  "fin"),
    ("DPRP-Information Technology",          "it"),
    ("DPRP-Human Resource Department",       "hr"),
    ("DPRP-Admin Department",                "admin"),
    ("DPRP-Health, Safety and Environmen",   "hse"),
    ("DPRP-Marine-Operation",                "marine"),
    ("DPRP-Logistics Dept",                  "logistics"),
    ("DORC-Finance And Accounts",            "dorc.fin"),
    ("DORC-Human Resources",                 "dorc.hr"),
    ("DORC-Administration Department",       "dorc.admin"),
    ("Refinery Laboratory",                  "ref.lab"),
    ("RFCC Block - Mechanical",              "rfcc.mech"),
    ("Utility Block - Mechanical",           "util.mech"),
    ("Crude Distillation Unit - Mechanical", "cdu.mech"),
    ("Polymer Block - Mechanical",           "poly.mech"),
]

DEPT_BUDGET_USD = 500_000.00   # illustrative monthly allocation per dept


def _make_dept_users(department: str, slug: str) -> list[dict]:
    return [
        {
            "email": f"hod.{slug}@dangote.com",
            "display_name": f"HOD – {department}",
            "role": "hod",
            "department": department,
            "password": "HOD@12345",
        },
        {
            "email": f"originator.{slug}@dangote.com",
            "display_name": f"Originator – {department}",
            "role": "originator",
            "department": department,
            "password": "Orig@1234",
        },
    ]


def seed_users(db) -> User:
    """Seed all users. Returns the IT admin user for use as exchange-rate updater."""
    all_users = list(ROLE_USERS)
    for dept, slug in SAMPLE_DEPARTMENTS:
        all_users.extend(_make_dept_users(dept, slug))

    it_admin_user = None
    for u in all_users:
        existing = db.query(User).filter(User.email == u["email"]).first()
        if existing:
            print(f"  SKIP  {u['email']} (already exists)")
            if existing.role == "it_admin":
                it_admin_user = existing
            continue
        user = User(
            email=u["email"],
            display_name=u["display_name"],
            role=u["role"],
            department=u.get("department"),
            hashed_password=_hash_password(u["password"]),
            is_active=True,
        )
        db.add(user)
        db.flush()
        if user.role == "it_admin":
            it_admin_user = user
        print(f"  ADD   {user.email} ({user.role})")

    db.commit()
    return it_admin_user


def seed_exchange_rates(db, updated_by_id: int) -> None:
    for rate_data in EXCHANGE_RATES:
        existing = (
            db.query(ExchangeRate)
            .filter(
                ExchangeRate.currency == rate_data["currency"],
                ExchangeRate.effective_from == TODAY,
            )
            .first()
        )
        if existing:
            print(f"  SKIP  ExchangeRate {rate_data['currency']} (today's rate exists)")
            continue
        rate = ExchangeRate(
            currency=rate_data["currency"],
            rate_to_usd=rate_data["rate_to_usd"],
            effective_from=TODAY,
            valid_until=None,
            updated_by=updated_by_id,
            source=rate_data["source"],
        )
        db.add(rate)
        print(f"  ADD   ExchangeRate {rate.currency} = {rate.rate_to_usd}")
    db.commit()


def seed_budgets(db) -> None:
    for dept, _slug in SAMPLE_DEPARTMENTS:
        existing = (
            db.query(CategoryBudget)
            .filter(
                CategoryBudget.department == dept,
                CategoryBudget.month == CURRENT_MONTH,
                CategoryBudget.year == CURRENT_YEAR,
            )
            .first()
        )
        if existing:
            print(f"  SKIP  Budget {dept} {CURRENT_MONTH}/{CURRENT_YEAR}")
            continue
        budget = CategoryBudget(
            department=dept,
            month=CURRENT_MONTH,
            year=CURRENT_YEAR,
            monthly_allocation_usd=DEPT_BUDGET_USD,
            monthly_allocation_ngn=DEPT_BUDGET_USD * 1600,
            annual_allocation_usd=DEPT_BUDGET_USD * 12,
        )
        db.add(budget)
        print(f"  ADD   Budget {dept} {CURRENT_MONTH}/{CURRENT_YEAR} = ${DEPT_BUDGET_USD:,.0f}")
    db.commit()


def main() -> None:
    print("=" * 60)
    print("DPRP Cash Call — Development Seed")
    print("=" * 60)
    db = SessionLocal()
    try:
        print("\n[1/3] Seeding users …")
        it_admin = seed_users(db)

        print("\n[2/3] Seeding exchange rates …")
        seed_exchange_rates(db, updated_by_id=it_admin.id)

        print("\n[3/3] Seeding category budgets …")
        seed_budgets(db)

        print("\n" + "=" * 60)
        print("Seed complete.")
        print("\nDev login credentials (all roles):")
        print("-" * 40)
        rows = [
            ("finance.reviewer@dangote.com", "Finance@123",  "finance_reviewer"),
            ("cfo@dangote.com",              "CFO@12345",    "cfo"),
            ("ceo@dangote.com",              "CEO@12345",    "ceo"),
            ("treasury@dangote.com",         "Treasury@123", "treasury"),
            ("it.admin@dangote.com",         "ITAdmin@123",  "it_admin"),
            ("hod.fin@dangote.com",          "HOD@12345",    "hod  (Finance dept)"),
            ("originator.fin@dangote.com",   "Orig@1234",    "originator (Finance dept)"),
        ]
        for email, pwd, role in rows:
            print(f"  {role:<30} {email:<35} {pwd}")
        print("=" * 60)

    except IntegrityError as exc:
        db.rollback()
        print(f"IntegrityError: {exc}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
