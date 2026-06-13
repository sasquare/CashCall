"""add system_audit_log table

Revision ID: a1b2c3d4e5f6
Revises: 18feaeb4a6c9
Create Date: 2026-06-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "18feaeb4a6c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("performed_by", sa.Integer(), nullable=False),
        sa.Column(
            "performed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["performed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_system_audit_log_id", "system_audit_log", ["id"])
    op.create_index("ix_system_audit_log_event_type", "system_audit_log", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_system_audit_log_event_type", table_name="system_audit_log")
    op.drop_index("ix_system_audit_log_id", table_name="system_audit_log")
    op.drop_table("system_audit_log")
