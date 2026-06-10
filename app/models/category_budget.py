from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CategoryBudget(Base):
    """
    One row per (department × month × year).
    Tracks allocation and running spend totals for the budget dashboard.
    """

    __tablename__ = "category_budgets"
    __table_args__ = (
        UniqueConstraint("department", "month", "year", name="uq_budget_dept_month_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Validated against ALL_DEPARTMENTS at app layer
    department: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    month: Mapped[int] = mapped_column(Integer, nullable=False)   # 1–12
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    monthly_allocation_usd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    monthly_allocation_ngn: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    annual_allocation_usd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)

    # Running totals — updated by the approval engine
    approved_mtd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    paid_mtd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    approved_ytd: Mapped[float] = mapped_column(Numeric(18, 2), default=0)

    # Pre-reserved amount from CFO-deferred payments arriving this month
    deferred_approved: Mapped[float] = mapped_column(Numeric(18, 2), default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<CategoryBudget {self.department} {self.month}/{self.year}>"
