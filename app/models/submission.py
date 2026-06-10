from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Human-readable unique ID: SC-2025-0001
    submission_id: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)

    department: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False)       # 1–12
    month_name: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g. "Jan-26"
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    cost_type: Mapped[str] = mapped_column(String(10), nullable=False)   # opex | capex
    supporting_justification: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending_hod", index=True)
    request_type: Mapped[str] = mapped_column(String(20), nullable=False, default="standard")

    urgency_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    urgency_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requested_payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    finance_authoriser: Mapped[str | None] = mapped_column(String(255), nullable=True)

    budget_over_limit_flag: Mapped[bool] = mapped_column(Boolean, default=False)

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
    cfo_decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cfo_approved_amount: Mapped[float | None] = mapped_column(String(20), nullable=True)
    cfo_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cfo_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cfo_decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cfo_post_deferral: Mapped[bool] = mapped_column(Boolean, default=False)
    cfo_post_deferral_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cfo_post_defer_to_month: Mapped[int | None] = mapped_column(Integer, nullable=True)

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

    # --- Metadata ---
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Relationships
    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by], back_populates="submissions")  # noqa: F821
    hod_approver: Mapped["User | None"] = relationship("User", foreign_keys=[hod_decided_by])  # noqa: F821
    finance_qc_approver: Mapped["User | None"] = relationship("User", foreign_keys=[finance_qc_by])  # noqa: F821
    cfo_approver: Mapped["User | None"] = relationship("User", foreign_keys=[cfo_decided_by])  # noqa: F821
    ceo_approver: Mapped["User | None"] = relationship("User", foreign_keys=[ceo_decided_by])  # noqa: F821
    treasury_officer: Mapped["User | None"] = relationship("User", foreign_keys=[treasury_updated_by])  # noqa: F821

    line_items: Mapped[list["LineItem"]] = relationship(  # noqa: F821
        "LineItem", back_populates="submission", cascade="all, delete-orphan"
    )
    audit_log: Mapped[list["AuditLog"]] = relationship(  # noqa: F821
        "AuditLog", back_populates="submission", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Submission {self.submission_id} status={self.status}>"
