from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LineItem(Base):
    """
    Each line item now carries its own independent approval status — an
    approved item advances to the next stage on its own, even while sibling
    items in the same submission are still pending or get rejected. The
    submission's own `status` field is a derived rollup (see
    submission_service.recompute_submission_status) used for list/queue
    display; this row's `status` is the real source of truth.
    """

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

    # ------------------------------------------------------------------
    # Per-item approval pipeline
    # ------------------------------------------------------------------

    # pending_hod | hod_rejected | pending_finance_qc | qc_query_raised |
    # finance_rejected | pending_cfo | cfo_rejected | deferred_by_cfo |
    # pending_ceo | ceo_rejected | pending_treasury_payment | paid
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_hod", index=True)

    # --- HOD stage ---
    hod_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    hod_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    hod_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hod_decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # --- Finance QC stage ---
    finance_qc_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    finance_qc_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    finance_qc_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finance_qc_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # --- CFO stage ---
    cfo_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)  # approved | rejected | deferred
    cfo_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cfo_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cfo_decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cfo_deferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cfo_defer_to_month: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- CEO stage ---
    ceo_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ceo_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ceo_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ceo_decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # --- Treasury stage ---
    treasury_payment_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    treasury_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    treasury_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    treasury_updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    submission: Mapped["Submission"] = relationship("Submission", back_populates="line_items")  # noqa: F821
    hod_approver: Mapped["User | None"] = relationship("User", foreign_keys=[hod_decided_by])  # noqa: F821
    finance_qc_approver: Mapped["User | None"] = relationship("User", foreign_keys=[finance_qc_by])  # noqa: F821
    cfo_approver: Mapped["User | None"] = relationship("User", foreign_keys=[cfo_decided_by])  # noqa: F821
    ceo_approver: Mapped["User | None"] = relationship("User", foreign_keys=[ceo_decided_by])  # noqa: F821
    treasury_officer: Mapped["User | None"] = relationship("User", foreign_keys=[treasury_updated_by])  # noqa: F821

    def __repr__(self) -> str:
        return f"<LineItem {self.vendor_name} {self.currency}{self.original_amount} status={self.status}>"
