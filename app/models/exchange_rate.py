from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # One of: USD, NGN, EUR, GBP, INR — validated at app layer
    currency: Mapped[str] = mapped_column(String(10), nullable=False)

    # USD is always 1.0; others are units-of-currency per 1 USD
    rate_to_usd: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    updater: Mapped["User"] = relationship("User", foreign_keys=[updated_by])  # noqa: F821

    def __repr__(self) -> str:
        return f"<ExchangeRate {self.currency} @ {self.rate_to_usd} from {self.effective_from}>"
