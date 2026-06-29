"""Position sizing models for the backtest engine.

Two methods, both ATR-driven (rolling std of spread as volatility proxy):
- FixedFractionalSizing: risk a fixed % of equity per trade
- ATRSizing: same formula with distinct naming for clarity in sweep configs

Both include a max-leverage cap so no single trade exceeds a hard notional limit.
The quantity returned is in "units" (bbls for a spread quoted in $/bbl), not
exchange contracts - divide by 1000 mentally to get approximate WTI/Brent lots.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd


class SizingModel(ABC):
    @abstractmethod
    def compute_size(self, equity: float, spread_price: float, atr: float) -> int:
        """Return number of units to trade (always >= 1)."""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def as_dict(self) -> dict: ...


class FixedFractionalSizing(SizingModel):
    """Risk a fixed fraction of equity per trade.

    qty = floor(equity x risk_pct / max(atr, min_atr))
    Capped at floor(max_leverage x equity / |spread_price|).

    Parameters
    ----------
    risk_pct : float
        Fraction of equity to risk per trade (e.g., 0.01 = 1%).
    max_leverage : float
        Hard notional leverage cap (total position / equity).
    min_atr : float
        Floor for ATR to prevent division-by-zero on quiet days.
    """

    def __init__(
        self,
        risk_pct: float = 0.01,
        max_leverage: float = 5.0,
        min_atr: float = 0.10,
    ) -> None:
        self.risk_pct = risk_pct
        self.max_leverage = max_leverage
        self.min_atr = min_atr

    def compute_size(self, equity: float, spread_price: float, atr: float) -> int:
        atr_safe = max(float(atr), self.min_atr)
        raw = equity * self.risk_pct / atr_safe

        lev_cap = (self.max_leverage * equity / abs(spread_price)) if abs(spread_price) > 1e-8 else raw
        qty = int(min(raw, lev_cap))
        return max(1, qty)

    def name(self) -> str:
        return "fixed_fractional"

    def as_dict(self) -> dict:
        return {
            "sizing": self.name(),
            "risk_pct": self.risk_pct,
            "max_leverage": self.max_leverage,
            "min_atr": self.min_atr,
        }


class ATRSizing(SizingModel):
    """Volatility-adjusted sizing: position size scales inversely with ATR.

    Identical formula to FixedFractionalSizing but named distinctly so sweep
    configs can select it explicitly and the distinction shows in the params_json.

    Parameters
    ----------
    risk_pct : float
        Fraction of equity to risk per trade (e.g., 0.01 = 1%).
    max_leverage : float
        Hard notional leverage cap.
    min_atr : float
        Floor for ATR.
    """

    def __init__(
        self,
        risk_pct: float = 0.01,
        max_leverage: float = 5.0,
        min_atr: float = 0.10,
    ) -> None:
        self.risk_pct = risk_pct
        self.max_leverage = max_leverage
        self.min_atr = min_atr

    def compute_size(self, equity: float, spread_price: float, atr: float) -> int:
        atr_safe = max(float(atr), self.min_atr)
        raw = equity * self.risk_pct / atr_safe

        lev_cap = (self.max_leverage * equity / abs(spread_price)) if abs(spread_price) > 1e-8 else raw
        qty = int(min(raw, lev_cap))
        return max(1, qty)

    def name(self) -> str:
        return "atr_sizing"

    def as_dict(self) -> dict:
        return {
            "sizing": self.name(),
            "risk_pct": self.risk_pct,
            "max_leverage": self.max_leverage,
            "min_atr": self.min_atr,
        }


def compute_atr_series(spread_series: pd.Series, window: int = 14) -> pd.Series:
    """Rolling std of the spread as ATR proxy (shifted to avoid look-ahead).

    True ATR requires H/L/C bars. For a spread series quoted in $/bbl, the
    rolling std over ``window`` days serves as the volatility proxy used to
    scale position sizes.
    """
    return spread_series.rolling(window, min_periods=max(1, window // 2)).std().shift(1).bfill()
