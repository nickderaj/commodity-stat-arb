"""add contract_metrics table

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contract_metrics",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("realised_vol_20d", sa.Float()),
        sa.Column("hl_range_pct", sa.Float()),
        sa.Column("avg_volume_20d", sa.Float()),
        sa.Column("avg_oi_20d", sa.Float()),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_id", "date", name="uq_contract_metrics_contract_date"),
    )
    op.create_index(
        "ix_contract_metrics_contract_date",
        "contract_metrics",
        ["contract_id", "date"],
    )


def downgrade() -> None:
    op.drop_index("ix_contract_metrics_contract_date", table_name="contract_metrics")
    op.drop_table("contract_metrics")
