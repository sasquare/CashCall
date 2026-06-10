from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator, model_validator


class LineItemIn(BaseModel):
    vendor_name: str
    invoice_no: str
    po_number: str | None = None
    description: str
    items_products: str | None = None
    category: str
    account_code: str
    billing_period_start: date
    billing_period_end: date
    payment_tracking_code: str | None = None
    frequency: str
    status_remarks: str | None = None
    currency: str
    original_amount: Decimal
    is_arrear: bool = False
    arrear_type: str | None = None

    @field_validator("original_amount")
    @classmethod
    def amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Amount must be greater than zero.")
        return v

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, v: str) -> str:
        from app.constants import CURRENCIES
        if v not in CURRENCIES:
            raise ValueError(f"Invalid currency: {v}")
        return v

    @field_validator("category")
    @classmethod
    def valid_category(cls, v: str) -> str:
        from app.constants import CASH_CALL_CATEGORIES
        if v not in CASH_CALL_CATEGORIES:
            raise ValueError(f"Invalid category: {v}")
        return v

    @field_validator("frequency")
    @classmethod
    def valid_frequency(cls, v: str) -> str:
        from app.constants import PAYMENT_FREQUENCIES
        if v not in PAYMENT_FREQUENCIES:
            raise ValueError(f"Invalid frequency: {v}")
        return v

    @model_validator(mode="after")
    def arrear_type_required_when_arrear(self) -> "LineItemIn":
        if self.is_arrear and not self.arrear_type:
            raise ValueError("Arrear type is required when item is marked as an arrear.")
        return self


class SubmissionIn(BaseModel):
    department: str
    month: int
    year: int
    cost_type: str
    supporting_justification: str
    line_items: list[LineItemIn]

    @field_validator("month")
    @classmethod
    def valid_month(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError("Month must be between 1 and 12.")
        return v

    @field_validator("cost_type")
    @classmethod
    def valid_cost_type(cls, v: str) -> str:
        if v not in ("opex", "capex"):
            raise ValueError("Cost type must be opex or capex.")
        return v

    @field_validator("line_items")
    @classmethod
    def at_least_one_item(cls, v: list) -> list:
        if not v:
            raise ValueError("At least one line item is required.")
        if len(v) > 10:
            raise ValueError("Maximum 10 line items per submission.")
        return v
