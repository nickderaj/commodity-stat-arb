"""Portfolio state tracker for the backtest engine.

Tracks cash, open position, realised/unrealised PnL, equity curve, and max drawdown.
Stores a completed trade log for metric computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class Trade:
    entry_date: date
    exit_date: date
    direction: int          # +1 long spread, -1 short spread
    entry_price: float
    exit_price: float
    fill_price: float
    zscore_at_entry: float
    regime_at_entry: str
    pnl: float              # net PnL after costs
    quantity: int = 1       # number of units/contracts traded
    fees: float = 0.0
    slippage: float = 0.0
    spread_cost: float = 0.0
    temp_impact_cost: float = 0.0
    perm_impact_cost: float = 0.0

    @property
    def duration_days(self) -> int:
        return (self.exit_date - self.entry_date).days


class Portfolio:
    """Tracks positions, cash, realised PnL, unrealised PnL, and max drawdown.

    Position is +1 (long spread), -1 (short spread), or 0 (flat).
    Unit-size: one contract per trade. Phase 5 adds proper sizing via sizing.py.
    """

    def __init__(self, initial_capital: float = 100_000.0) -> None:
        self.initial_capital = initial_capital
        self.cash: float = initial_capital
        self.position: int = 0
        self.entry_price: Optional[float] = None
        self.entry_date: Optional[date] = None
        self.entry_zscore: Optional[float] = None
        self.entry_regime: str = ""
        self.entry_quantity: int = 1
        self.realised_pnl: float = 0.0
        self._equity_curve: list[tuple[date, float]] = []
        self.trades: list[Trade] = []

    # ------------------------------------------------------------------
    # Trade lifecycle
    # ------------------------------------------------------------------

    def on_entry(
        self,
        bar_date: date,
        price: float,
        direction: int,
        zscore: float = float("nan"),
        regime: str = "",
        quantity: int = 1,
    ) -> None:
        if self.position != 0:
            raise RuntimeError("Cannot enter when already in position")
        if direction not in (-1, 1):
            raise ValueError(f"direction must be +1 or -1, got {direction}")
        self.position = direction
        self.entry_price = price
        self.entry_date = bar_date
        self.entry_zscore = zscore
        self.entry_regime = regime
        self.entry_quantity = max(1, int(quantity))

    def on_exit(
        self,
        bar_date: date,
        price: float,
        fees: float = 0.0,
        slippage: float = 0.0,
        spread_cost: float = 0.0,
        temp_impact_cost: float = 0.0,
        perm_impact_cost: float = 0.0,
    ) -> Trade:
        if self.position == 0:
            raise RuntimeError("Cannot exit when flat")
        raw_pnl = (price - self.entry_price) * self.position * self.entry_quantity
        total_cost = fees + slippage + spread_cost + temp_impact_cost + perm_impact_cost
        net_pnl = raw_pnl - total_cost
        self.realised_pnl += net_pnl
        self.cash += net_pnl

        trade = Trade(
            entry_date=self.entry_date,
            exit_date=bar_date,
            direction=self.position,
            entry_price=self.entry_price,
            exit_price=price,
            fill_price=price,
            zscore_at_entry=self.entry_zscore if self.entry_zscore is not None else float("nan"),
            regime_at_entry=self.entry_regime,
            pnl=net_pnl,
            quantity=self.entry_quantity,
            fees=fees,
            slippage=slippage,
            spread_cost=spread_cost,
            temp_impact_cost=temp_impact_cost,
            perm_impact_cost=perm_impact_cost,
        )
        self.trades.append(trade)

        self.position = 0
        self.entry_price = None
        self.entry_date = None
        self.entry_zscore = None
        self.entry_regime = ""
        self.entry_quantity = 1

        return trade

    def mark_to_market(self, bar_date: date, price: float) -> float:
        """Record equity snapshot; returns current equity (cash + unrealised PnL)."""
        unrealised = 0.0
        if self.position != 0 and self.entry_price is not None:
            unrealised = (price - self.entry_price) * self.position * self.entry_quantity
        equity = self.cash + unrealised
        self._equity_curve.append((bar_date, equity))
        return equity

    # ------------------------------------------------------------------
    # Performance metrics
    # ------------------------------------------------------------------

    def equity_series(self) -> pd.Series:
        if not self._equity_curve:
            return pd.Series(dtype=float)
        dates, vals = zip(*self._equity_curve)
        return pd.Series(list(vals), index=pd.to_datetime(list(dates)), name="equity")

    def daily_pnl_series(self) -> pd.Series:
        return self.equity_series().diff().dropna()

    def max_drawdown(self) -> float:
        """Maximum peak-to-trough drawdown as a fraction (negative number)."""
        eq = self.equity_series()
        if eq.empty:
            return 0.0
        peak = eq.cummax()
        dd = (eq - peak) / peak.replace(0, np.nan)
        return float(dd.min())

    def sharpe(self) -> float:
        pnl = self.daily_pnl_series()
        if len(pnl) < 5 or pnl.std() < 1e-10:
            return float("nan")
        return float(np.sqrt(252) * pnl.mean() / pnl.std())

    def sortino(self) -> float:
        pnl = self.daily_pnl_series()
        downside = pnl[pnl < 0]
        if len(pnl) < 5 or len(downside) == 0 or downside.std() < 1e-10:
            return float("nan")
        return float(np.sqrt(252) * pnl.mean() / downside.std())

    def calmar(self) -> float:
        eq = self.equity_series()
        if eq.empty:
            return float("nan")
        n_years = len(eq) / 252
        total_return = (eq.iloc[-1] - self.initial_capital) / self.initial_capital
        ann_return = (1 + total_return) ** (1 / max(n_years, 1e-6)) - 1
        mdd = abs(self.max_drawdown())
        if mdd < 1e-10:
            return float("nan")
        return float(ann_return / mdd)

    def win_rate(self) -> float:
        if not self.trades:
            return float("nan")
        return float(sum(1 for t in self.trades if t.pnl > 0) / len(self.trades))

    def profit_factor(self) -> float:
        wins = sum(t.pnl for t in self.trades if t.pnl > 0)
        losses = sum(abs(t.pnl) for t in self.trades if t.pnl < 0)
        if losses < 1e-10:
            return float("nan")
        return float(wins / losses)

    def avg_trade_pnl(self) -> float:
        if not self.trades:
            return float("nan")
        return float(np.mean([t.pnl for t in self.trades]))

    def avg_trade_duration_days(self) -> float:
        if not self.trades:
            return float("nan")
        return float(np.mean([t.duration_days for t in self.trades]))

    def summary(self) -> dict:
        return {
            "total_trades": len(self.trades),
            "realised_pnl": self.realised_pnl,
            "sharpe": self.sharpe(),
            "sortino": self.sortino(),
            "calmar": self.calmar(),
            "max_drawdown": self.max_drawdown(),
            "win_rate": self.win_rate(),
            "profit_factor": self.profit_factor(),
            "avg_trade_pnl": self.avg_trade_pnl(),
            "avg_trade_duration_days": self.avg_trade_duration_days(),
        }
