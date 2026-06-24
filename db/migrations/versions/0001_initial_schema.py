"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-24 14:48:52.617903

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("product", sa.String(10), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("contract_month", sa.String(20), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("first_notice_date", sa.Date()),
        sa.Column("last_trade_date", sa.Date()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", name="uq_contracts_ticker"),
    )
    op.create_index("ix_contracts_product_expiry", "contracts", ["product", "expiry"])

    op.create_table(
        "ohlcv_bars",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float()),
        sa.Column("high", sa.Float()),
        sa.Column("low", sa.Float()),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.BigInteger()),
        sa.Column("open_interest", sa.BigInteger()),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_id", "date", name="uq_ohlcv_contract_date"),
    )
    op.create_index("ix_ohlcv_contract_date", "ohlcv_bars", ["contract_id", "date"])

    op.create_table(
        "roll_calendar",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product", sa.String(10), nullable=False),
        sa.Column("contract_month", sa.String(20), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("first_notice_date", sa.Date()),
        sa.Column("last_trade_date", sa.Date()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product", "contract_month", name="uq_roll_product_month"),
    )

    op.create_table(
        "spreads",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("spread_name", sa.String(50), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("leg1_price", sa.Float()),
        sa.Column("leg2_price", sa.Float()),
        sa.Column("hedge_ratio", sa.Float(), server_default="1.0"),
        sa.Column("roll_window_flag", sa.Boolean(), server_default="false"),
        sa.Column("regime", sa.String(20)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("spread_name", "date", name="uq_spread_name_date"),
    )
    op.create_index("ix_spreads_name_date", "spreads", ["spread_name", "date"])

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("params_hash", sa.String(64), nullable=False),
        sa.Column("spread_name", sa.String(50), nullable=False),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("sharpe", sa.Float()),
        sa.Column("sortino", sa.Float()),
        sa.Column("calmar", sa.Float()),
        sa.Column("max_drawdown", sa.Float()),
        sa.Column("total_trades", sa.Integer()),
        sa.Column("win_rate", sa.Float()),
        sa.Column("profit_factor", sa.Float()),
        sa.Column("avg_trade_pnl", sa.Float()),
        sa.Column("avg_trade_duration_days", sa.Float()),
        sa.Column("params_json", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("params_hash", name="uq_backtest_params_hash"),
    )

    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("spread_name", sa.String(50), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("zscore", sa.Float()),
        sa.Column("lookback", sa.Integer()),
        sa.Column("entry_flag", sa.Boolean(), server_default="false"),
        sa.Column("exit_flag", sa.Boolean(), server_default="false"),
        sa.Column("regime_flags", sa.Text()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "spread_name", "date", "lookback", name="uq_signal_spread_date_lookback"
        ),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("spread_name", sa.String(50), nullable=False),
        sa.Column("backtest_run_id", sa.Integer()),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("exit_date", sa.Date()),
        sa.Column("direction", sa.String(5), nullable=False),
        sa.Column("entry_price", sa.Float()),
        sa.Column("exit_price", sa.Float()),
        sa.Column("fill_price", sa.Float()),
        sa.Column("fees", sa.Float(), server_default="0"),
        sa.Column("slippage", sa.Float(), server_default="0"),
        sa.Column("spread_cost", sa.Float(), server_default="0"),
        sa.Column("temp_impact_cost", sa.Float(), server_default="0"),
        sa.Column("perm_impact_cost", sa.Float(), server_default="0"),
        sa.Column("pnl", sa.Float()),
        sa.Column("zscore_at_entry", sa.Float()),
        sa.Column("regime_at_entry", sa.String(50)),
        sa.Column("trade_duration_days", sa.Integer()),
        sa.Column("created_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_spread_entry", "orders", ["spread_name", "entry_date"])


def downgrade() -> None:
    op.drop_table("orders")
    op.drop_table("signals")
    op.drop_table("backtest_runs")
    op.drop_table("spreads")
    op.drop_table("roll_calendar")
    op.drop_table("ohlcv_bars")
    op.drop_table("contracts")
