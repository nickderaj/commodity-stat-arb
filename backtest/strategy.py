"""Strategy base class and ZScoreStrategy implementation.

The engine calls strategy.on_bar(idx, current_position) on each bar iteration.
Strategies pre-compute all signals in load_data() using shift(1) to guarantee
zero look-ahead bias - signals at bar t use data through bar t-1 only.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from research.signals import (
    compute_filter_masks,
    compute_zscore,
    load_front_month_volume,
    load_spread_df,
)


class Strategy(ABC):
    """Abstract strategy base class.

    Subclasses pre-compute all indicator series in load_data() using shift(1) or
    equivalent so that on_bar() never accesses future data.
    """

    @abstractmethod
    def load_data(
        self,
        spread_name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Load spread data and pre-compute required series. Returns the spread DataFrame."""

    @abstractmethod
    def on_bar(self, idx: int, current_position: int) -> int:
        """Return desired position for bar at index idx.

        Parameters
        ----------
        idx : int
            Bar index into the spread DataFrame.
        current_position : int
            Portfolio's current position (+1, -1, or 0) BEFORE this bar is processed.

        Returns
        -------
        int
            Desired position: +1 (long spread), -1 (short spread), 0 (flat).
            Returning ``current_position`` means hold; the engine takes no action.
        """

    @abstractmethod
    def get_bar_meta(self, idx: int) -> dict:
        """Return per-bar metadata for audit logging (zscore, regime, suppress)."""

    @property
    @abstractmethod
    def params(self) -> dict:
        """Return strategy parameters as a JSON-serialisable dict for DB storage."""


class ZScoreStrategy(Strategy):
    """Z-score mean-reversion strategy.

    Entry: |z| > entry_threshold  →  short if z > 0, long if z < 0
    Exit:  |z| < exit_threshold
    Filters: roll-window + vol + liquidity suppression (blocks new entries only)

    Look-ahead bias note
    --------------------
    ``compute_zscore`` applies ``shift(1)`` so that zscore.iloc[t] is computed
    from bars 0 … t-1.  on_bar() reads only zscore.iloc[idx], guaranteeing that
    the decision at bar t uses no data from t or later.
    """

    # Map spread names to their underlying product ticker for volume loading
    _PRODUCT_MAP: dict[str, Optional[str]] = {
        "wti_calendar": "CL",
        "brent_calendar": "BZ",
        "brent_wti": None,
    }

    def __init__(
        self,
        entry_threshold: float = 1.5,
        exit_threshold: float = 0.5,
        lookback: int = 30,
        use_filters: bool = True,
    ) -> None:
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.lookback = lookback
        self.use_filters = use_filters

        self._df: Optional[pd.DataFrame] = None
        self._zscore: Optional[pd.Series] = None
        self._suppress: Optional[pd.Series] = None

    def load_data(
        self,
        spread_name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        df = load_spread_df(spread_name)
        if start_date:
            df = df[df.index >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df.index <= pd.Timestamp(end_date)]

        product = self._PRODUCT_MAP.get(spread_name)
        volume = load_front_month_volume(product) if product else None

        # shift(1) inside compute_zscore ensures no look-ahead bias
        self._zscore = compute_zscore(df["value"], self.lookback)

        filters_df = compute_filter_masks(df, volume=volume)
        self._suppress = (
            filters_df["any_suppress"]
            if self.use_filters
            else pd.Series(False, index=df.index)
        )

        self._df = df
        return df

    def on_bar(self, idx: int, current_position: int) -> int:
        """Return desired position using pre-computed (look-ahead-free) z-score."""
        assert self._zscore is not None, "Call load_data() before running the engine"

        z = self._zscore.iloc[idx]
        if np.isnan(z):
            return current_position  # no signal → hold

        if current_position == 0:
            # Flat: check for entry (suppression blocks new entries only)
            suppressed = bool(self._suppress.iloc[idx]) if self._suppress is not None else False
            if suppressed:
                return 0
            if z > self.entry_threshold:
                return -1   # short spread: expect reversion down
            if z < -self.entry_threshold:
                return 1    # long spread: expect reversion up
            return 0

        else:
            # In position: only check exit; suppression does not force exit
            if abs(z) < self.exit_threshold:
                return 0    # exit
            return current_position  # hold

    def get_bar_meta(self, idx: int) -> dict:
        assert self._zscore is not None
        z = self._zscore.iloc[idx]
        suppressed = bool(self._suppress.iloc[idx]) if self._suppress is not None else False
        regime = str(self._df["regime"].iloc[idx]) if self._df is not None else ""
        return {
            "zscore": float(z) if not np.isnan(z) else None,
            "regime": regime,
            "suppressed": suppressed,
        }

    @property
    def params(self) -> dict:
        return {
            "strategy": "ZScoreStrategy",
            "entry_threshold": self.entry_threshold,
            "exit_threshold": self.exit_threshold,
            "lookback": self.lookback,
            "use_filters": self.use_filters,
        }
