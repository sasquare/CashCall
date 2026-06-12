from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), nullable=False, index=True)

    action: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(100), nullable=False)

    performed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    amount_usd: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    submission: Mapped["Submission"] = relationship("Submission", back_populates="audit_log")  # noqa: F821
    performer: Mapped["User"] = relationship("User", back_populates="audit_entries")  # noqa: F821

    def __repr__(self) -> str:
        return f"<AuditLog submission={self.submission_id} action={self.action}>"
