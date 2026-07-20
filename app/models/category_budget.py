from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CategoryBudget(Base):
    """
    One row per (category × cost_type × month × year).
    Budgets are company-wide per spend category — not per department.
    Tracks allocation and running spend totals for the budget dashboard.
    """

    __tablename__ = "category_budgets"
    __table_args__ = (
        UniqueConstraint("category", "cost_type", "month", "year", name="uq_budget_category_costtype_month_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Validated against CASH_CALL_CATEGORIES at app layer
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    cost_type: Mapped[str] = mapped_column(String(10), nullable=False, default="opex")  # opex | capex

    month: Mapped[int] = mapped_column(Integer, nullable=False)   # 1–12
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    monthly_allocation_usd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)

    # Running totals — updated by the approval engine
    approved_mtd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    paid_mtd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    approved_ytd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)

    # Amount reserved by CFO-deferred line items landing in this month
    deferred_approved: Mapped[float] = mapped_column(Numeric(18, 2), default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<CategoryBudget {self.category} ({self.cost_type}) {self.month}/{self.year}>"
