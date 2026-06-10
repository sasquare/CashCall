from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LineItem(Base):
    __tablename__ = "line_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), nullable=False, index=True)

    vendor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    invoice_no: Mapped[str] = mapped_column(String(100), nullable=False)
    po_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    items_products: Mapped[str | None] = mapped_column(Text, nullable=True)

    # One of the 5 cash call categories
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    account_code: Mapped[str] = mapped_column(String(50), nullable=False)

    billing_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    billing_period_end: Mapped[date] = mapped_column(Date, nullable=False)

    payment_tracking_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)  # one_off | monthly | quarterly | annual
    status_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Currency fields
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    original_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)

    # Stamped at submission time — immutable thereafter
    equivalent_usd: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    exchange_rate_used: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)

    # Set at CEO approval stage
    approved_usd: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    # Arrear flags
    is_arrear: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    arrear_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # CFO deferral
    cfo_deferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cfo_defer_to_month: Mapped[int | None] = mapped_column(Integer, nullable=True)

    submission: Mapped["Submission"] = relationship("Submission", back_populates="line_items")  # noqa: F821

    def __repr__(self) -> str:
        return f"<LineItem {self.vendor_name} {self.currency}{self.original_amount}>"
