"""add ts_regime column to spreads table

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("spreads", sa.Column("ts_regime", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("spreads", "ts_regime")
