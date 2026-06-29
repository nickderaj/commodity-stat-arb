"""add quantity column to orders table

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("quantity", sa.Integer(), nullable=True, server_default="1"))


def downgrade() -> None:
    op.drop_column("orders", "quantity")
