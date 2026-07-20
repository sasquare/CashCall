"""per-item approval pipeline: line items get their own status + per-stage fields

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("line_items") as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(length=30), nullable=False, server_default="pending_hod"))

        batch_op.add_column(sa.Column("hod_decision", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("hod_comment", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("hod_decided_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("hod_decided_by", sa.Integer(), nullable=True))

        batch_op.add_column(sa.Column("finance_qc_status", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("finance_qc_comment", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("finance_qc_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("finance_qc_by", sa.Integer(), nullable=True))

        batch_op.add_column(sa.Column("cfo_decision", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("cfo_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("cfo_decided_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("cfo_decided_by", sa.Integer(), nullable=True))

        batch_op.add_column(sa.Column("ceo_decision", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("ceo_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ceo_decided_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("ceo_decided_by", sa.Integer(), nullable=True))

        batch_op.add_column(sa.Column("treasury_payment_status", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("treasury_comment", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("treasury_updated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("treasury_updated_by", sa.Integer(), nullable=True))

        batch_op.create_foreign_key("fk_line_items_hod_decided_by", "users", ["hod_decided_by"], ["id"])
        batch_op.create_foreign_key("fk_line_items_finance_qc_by", "users", ["finance_qc_by"], ["id"])
        batch_op.create_foreign_key("fk_line_items_cfo_decided_by", "users", ["cfo_decided_by"], ["id"])
        batch_op.create_foreign_key("fk_line_items_ceo_decided_by", "users", ["ceo_decided_by"], ["id"])
        batch_op.create_foreign_key("fk_line_items_treasury_updated_by", "users", ["treasury_updated_by"], ["id"])

    op.create_index("ix_line_items_status", "line_items", ["status"])

    with op.batch_alter_table("audit_log") as batch_op:
        batch_op.add_column(sa.Column("line_item_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_audit_log_line_item_id", "line_items", ["line_item_id"], ["id"])
    op.create_index("ix_audit_log_line_item_id", "audit_log", ["line_item_id"])

    # Existing rows: seed each line item's own status from its submission's
    # current status so nothing already in flight gets orphaned from queues.
    op.execute(
        "UPDATE line_items SET status = "
        "(SELECT s.status FROM submissions s WHERE s.id = line_items.submission_id) "
        "WHERE EXISTS (SELECT 1 FROM submissions s WHERE s.id = line_items.submission_id)"
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_line_item_id", table_name="audit_log")
    with op.batch_alter_table("audit_log") as batch_op:
        batch_op.drop_constraint("fk_audit_log_line_item_id", type_="foreignkey")
        batch_op.drop_column("line_item_id")

    op.drop_index("ix_line_items_status", table_name="line_items")
    with op.batch_alter_table("line_items") as batch_op:
        batch_op.drop_constraint("fk_line_items_hod_decided_by", type_="foreignkey")
        batch_op.drop_constraint("fk_line_items_finance_qc_by", type_="foreignkey")
        batch_op.drop_constraint("fk_line_items_cfo_decided_by", type_="foreignkey")
        batch_op.drop_constraint("fk_line_items_ceo_decided_by", type_="foreignkey")
        batch_op.drop_constraint("fk_line_items_treasury_updated_by", type_="foreignkey")

        batch_op.drop_column("status")
        batch_op.drop_column("hod_decision")
        batch_op.drop_column("hod_comment")
        batch_op.drop_column("hod_decided_at")
        batch_op.drop_column("hod_decided_by")
        batch_op.drop_column("finance_qc_status")
        batch_op.drop_column("finance_qc_comment")
        batch_op.drop_column("finance_qc_at")
        batch_op.drop_column("finance_qc_by")
        batch_op.drop_column("cfo_decision")
        batch_op.drop_column("cfo_reason")
        batch_op.drop_column("cfo_decided_at")
        batch_op.drop_column("cfo_decided_by")
        batch_op.drop_column("ceo_decision")
        batch_op.drop_column("ceo_reason")
        batch_op.drop_column("ceo_decided_at")
        batch_op.drop_column("ceo_decided_by")
        batch_op.drop_column("treasury_payment_status")
        batch_op.drop_column("treasury_comment")
        batch_op.drop_column("treasury_updated_at")
        batch_op.drop_column("treasury_updated_by")
