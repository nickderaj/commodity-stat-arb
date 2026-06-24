"""widen contract_month to varchar20

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-24 15:36:37.053270

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("contracts", "contract_month", type_=sa.String(20), existing_nullable=False)
    op.alter_column("roll_calendar", "contract_month", type_=sa.String(20), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("contracts", "contract_month", type_=sa.String(7), existing_nullable=False)
    op.alter_column("roll_calendar", "contract_month", type_=sa.String(7), existing_nullable=False)
