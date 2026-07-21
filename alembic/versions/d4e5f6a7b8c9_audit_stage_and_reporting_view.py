"""audit log stage/previous_status columns + Power BI reporting view

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Maps the "<stage>_" prefix on legacy audit_log.action values (e.g.
# "hod_approved") to the new stage column, so existing rows aren't left
# blank. Order matters: "finance_qc_" must be checked before "finance_".
_ACTION_PREFIX_TO_STAGE = [
    ("hod_", "hod"),
    ("finance_qc_", "finance_qc"),
    ("cfo_", "cfo"),
    ("ceo_", "ceo"),
    ("treasury_", "treasury"),
]


def upgrade() -> None:
    with op.batch_alter_table("audit_log") as batch_op:
        batch_op.add_column(sa.Column("stage", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("previous_status", sa.String(length=30), nullable=True))
        batch_op.create_index("ix_audit_log_stage", ["stage"])

    conn = op.get_bind()
    for prefix, stage in _ACTION_PREFIX_TO_STAGE:
        conn.execute(
            sa.text(
                "UPDATE audit_log SET stage = :stage "
                "WHERE stage IS NULL AND action LIKE :pattern"
            ),
            {"stage": stage, "pattern": f"{prefix}%"},
        )

    # Flattened, denormalized view for Power BI / reporting tools — joins
    # line item, submission, and creator into one queryable row per item so
    # a report author doesn't need to model the joins themselves. Read-only;
    # nothing in the application writes to this view.
    op.execute("""
        CREATE VIEW line_item_approval_report AS
        SELECT
            li.id                          AS line_item_id,
            s.submission_id                AS submission_code,
            s.department                   AS department,
            s.cost_type                    AS cost_type,
            s.month                        AS submission_month,
            s.year                         AS submission_year,
            s.request_type                 AS request_type,
            li.vendor_name                 AS vendor_name,
            li.invoice_no                  AS invoice_no,
            li.category                    AS category,
            li.currency                    AS currency,
            li.original_amount             AS original_amount,
            li.equivalent_usd              AS amount_usd,
            li.status                      AS current_status,
            li.is_arrear                   AS is_arrear,
            li.hod_decision                AS hod_decision,
            li.hod_decided_at              AS hod_decided_at,
            li.finance_qc_status           AS finance_qc_decision,
            li.finance_qc_at               AS finance_qc_decided_at,
            li.cfo_decision                AS cfo_decision,
            li.cfo_decided_at              AS cfo_decided_at,
            li.cfo_deferred                AS cfo_deferred,
            li.cfo_defer_to_month          AS cfo_defer_to_month,
            li.ceo_decision                AS ceo_decision,
            li.ceo_decided_at              AS ceo_decided_at,
            li.treasury_payment_status     AS treasury_payment_status,
            li.treasury_updated_at         AS treasury_updated_at,
            s.created_at                   AS submitted_at
        FROM line_items li
        JOIN submissions s ON s.id = li.submission_id
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS line_item_approval_report")
    with op.batch_alter_table("audit_log") as batch_op:
        batch_op.drop_index("ix_audit_log_stage")
        batch_op.drop_column("previous_status")
        batch_op.drop_column("stage")
