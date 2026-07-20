"""rework category_budgets to be keyed by category, not department

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-20 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Budgets were never actually department-scoped in practice (Finance allocates
    # by spend category, company-wide) — old department-keyed rows are discarded.
    op.drop_table("category_budgets")

    op.create_table(
        "category_budgets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("cost_type", sa.String(length=10), nullable=False, server_default="opex"),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("monthly_allocation_usd", sa.Numeric(18, 2), server_default="0"),
        sa.Column("approved_mtd", sa.Numeric(18, 2), server_default="0"),
        sa.Column("paid_mtd", sa.Numeric(18, 2), server_default="0"),
        sa.Column("approved_ytd", sa.Numeric(18, 2), server_default="0"),
        sa.Column("deferred_approved", sa.Numeric(18, 2), server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category", "cost_type", "month", "year", name="uq_budget_category_costtype_month_year"),
    )
    op.create_index("ix_category_budgets_id", "category_budgets", ["id"])
    op.create_index("ix_category_budgets_category", "category_budgets", ["category"])


def downgrade() -> None:
    op.drop_index("ix_category_budgets_category", table_name="category_budgets")
    op.drop_index("ix_category_budgets_id", table_name="category_budgets")
    op.drop_table("category_budgets")

    op.create_table(
        "category_budgets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("department", sa.String(length=255), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("monthly_allocation_usd", sa.Numeric(18, 2), server_default="0"),
        sa.Column("monthly_allocation_ngn", sa.Numeric(18, 2), server_default="0"),
        sa.Column("annual_allocation_usd", sa.Numeric(18, 2), server_default="0"),
        sa.Column("approved_mtd", sa.Numeric(18, 2), server_default="0"),
        sa.Column("paid_mtd", sa.Numeric(18, 2), server_default="0"),
        sa.Column("approved_ytd", sa.Numeric(18, 2), server_default="0"),
        sa.Column("deferred_approved", sa.Numeric(18, 2), server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("department", "month", "year", name="uq_budget_dept_month_year"),
    )
