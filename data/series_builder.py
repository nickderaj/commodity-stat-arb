"""Continuous series builder for commodity futures.

Takes individual contract OHLCV bars + roll calendar and stitches them into
continuous M1 (front-month) and M2 (second-month) series using either:

  - "calendar" mode: roll N days before expiry (configurable, default 5)
  - "oi" mode: roll when next contract open interest > front contract OI

Writes the resulting spread series to the `spreads` table.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from config.schema import SpreadDefinition
from data.roll_calendar import get_roll_dates
from db.models import Contract, OHLCVBar, Spread
from db.session import get_session


def _load_contract_bars(product: str, exchange: str, start: date, end: date) -> pd.DataFrame:
    """Load all OHLCV bars for a product+exchange from DB into a single DataFrame.

    Returns DataFrame with columns: date, contract_month, close, open_interest, volume.
    """
    session = get_session()
    try:
        rows = (
            session.query(OHLCVBar, Contract)
            .join(Contract, OHLCVBar.contract_id == Contract.id)
            .filter(
                Contract.product == product,
                Contract.exchange == exchange,
                OHLCVBar.date >= start,
                OHLCVBar.date <= end,
            )
            .order_by(OHLCVBar.date, Contract.expiry)
            .all()
        )
        records = [
            {
                "date": bar.date,
                "contract_month": contract.contract_month,
                "expiry": contract.expiry,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "open_interest": bar.open_interest,
            }
            for bar, contract in rows
        ]
        return pd.DataFrame(records)
    finally:
        session.close()


def _build_continuous_calendar_mode(
    bars: pd.DataFrame,
    roll_dates: pd.DataFrame,
    month_offset: int,
    roll_offset_days: int,
) -> pd.DataFrame:
    """Build continuous series using calendar-based roll.

    month_offset=0 → front month (M1), month_offset=1 → second month (M2), etc.
    """
    # Prefer actual individual contracts over the continuous yfinance proxy when both
    # are present; the proxy is only useful when no individual data exists at all.
    non_continuous = bars[bars["contract_month"] != "continuous"]
    if not non_continuous.empty:
        bars = non_continuous

    all_dates = sorted(bars["date"].unique())
    result_rows = []

    for d in all_dates:
        day_bars = bars[bars["date"] == d].sort_values("expiry")

        # Filter to contracts that haven't expired yet (expiry >= d)
        live = day_bars[day_bars["expiry"] >= d]
        if live.empty:
            continue

        # Determine which contracts to roll out of, considering roll_offset
        # A contract is "rolled" (unavailable) if it expires within roll_offset_days
        roll_cutoff = d + timedelta(days=roll_offset_days)
        active = live[live["expiry"] > roll_cutoff]

        # If no contracts pass the roll cutoff (i.e. we're in roll window), fall back to all live
        if active.empty:
            active = live

        if len(active) <= month_offset:
            continue

        target = active.iloc[month_offset]
        result_rows.append({
            "date": d,
            "contract_month": target["contract_month"],
            "expiry": target["expiry"],
            "close": target["close"],
            "open": target["open"],
            "high": target["high"],
            "low": target["low"],
            "volume": target["volume"],
            "open_interest": target["open_interest"],
        })

    return pd.DataFrame(result_rows).set_index("date") if result_rows else pd.DataFrame()


def _build_continuous_oi_mode(
    bars: pd.DataFrame,
    month_offset: int,
) -> pd.DataFrame:
    """Build continuous series using OI crossover roll.

    Rolls to the next contract when its open interest exceeds the current contract's OI.
    month_offset is applied after OI-based front contract selection.
    """
    all_dates = sorted(bars["date"].unique())
    result_rows = []

    for d in all_dates:
        day_bars = bars[bars["date"] == d].sort_values("expiry")
        live = day_bars[day_bars["expiry"] >= d].copy()
        if live.empty:
            continue

        # Rank by OI descending; NaN OI falls to the back
        live = live.sort_values("open_interest", ascending=False, na_position="last")

        if len(live) <= month_offset:
            continue

        target = live.iloc[month_offset]
        result_rows.append({
            "date": d,
            "contract_month": target["contract_month"],
            "expiry": target["expiry"],
            "close": target["close"],
            "open": target["open"],
            "high": target["high"],
            "low": target["low"],
            "volume": target["volume"],
            "open_interest": target["open_interest"],
        })

    return pd.DataFrame(result_rows).set_index("date") if result_rows else pd.DataFrame()


def _roll_window_flag(dates: pd.Index, roll_dates: pd.DataFrame, window_days: int = 5) -> pd.Series:
    """Return boolean Series: True if date is within window_days before expiry (inclusive)."""
    expiries = pd.to_datetime(roll_dates["expiry"].values)
    result = pd.Series(False, index=dates)
    for expiry in expiries:
        lower = (expiry - timedelta(days=window_days)).date()
        upper = expiry.date()
        mask = (dates >= lower) & (dates <= upper)
        result[mask] = True
    return result


class SeriesBuilder:
    """Builds continuous spread series from individual contract bars."""

    def __init__(self, spread: SpreadDefinition, start: date, end: date) -> None:
        self.spread = spread
        self.start = start
        self.end = end

    def build(self) -> pd.DataFrame:
        """Construct and return the spread DataFrame.

        Returns columns: date (index), value, leg1_price, leg2_price,
        hedge_ratio, roll_window_flag, regime.
        """
        leg_series = []
        for leg in self.spread.legs:
            product = leg.ticker.replace("=F", "")
            series = self._build_leg(product, leg.exchange, leg.month_offset)
            leg_series.append(series)

        if not leg_series or any(s.empty for s in leg_series):
            return pd.DataFrame()

        # Align on common dates
        combined = pd.concat([s.rename(f"leg{i}") for i, s in enumerate(leg_series)], axis=1)
        combined = combined.dropna()

        spread_value = sum(
            w * combined[f"leg{i}"]
            for i, w in enumerate(self.spread.weights)
        )

        # Roll calendar for leg 0 (primary leg)
        primary_product = self.spread.legs[0].ticker.replace("=F", "")
        roll_dates = get_roll_dates(primary_product, self.start, self.end)

        roll_flag = _roll_window_flag(
            combined.index, roll_dates, window_days=self.spread.roll_offset_days
        )
        regime = roll_flag.map({True: "roll_window", False: "mid_cycle"})

        df = pd.DataFrame({
            "value": spread_value,
            "leg1_price": combined["leg0"],
            "leg2_price": combined["leg1"] if len(leg_series) > 1 else float("nan"),
            "hedge_ratio": abs(self.spread.weights[1]) if len(self.spread.weights) > 1 else 1.0,
            "roll_window_flag": roll_flag,
            "regime": regime,
        })
        return df

    def _build_leg(self, product: str, exchange: str, month_offset: int) -> pd.Series:
        """Build a continuous price series for one leg."""
        bars = _load_contract_bars(product, exchange, self.start, self.end)
        if bars.empty:
            return pd.Series(dtype=float)

        roll_dates = get_roll_dates(product, self.start, self.end)

        if self.spread.roll_mode == "oi":
            df = _build_continuous_oi_mode(bars, month_offset)
        else:
            df = _build_continuous_calendar_mode(
                bars, roll_dates, month_offset, self.spread.roll_offset_days
            )

        if df.empty:
            return pd.Series(dtype=float)

        return df["close"]

    def save_to_db(self) -> None:
        """Build and persist spread series to the spreads table (upsert)."""
        df = self.build()
        if df.empty:
            print(f"No data to save for spread '{self.spread.name}'")
            return

        session = get_session()
        try:
            for d, row in df.iterrows():
                existing = (
                    session.query(Spread)
                    .filter_by(spread_name=self.spread.name, date=d)
                    .first()
                )
                entry = existing or Spread(spread_name=self.spread.name, date=d)
                entry.value = row["value"]
                entry.leg1_price = row["leg1_price"]
                entry.leg2_price = row["leg2_price"]
                entry.hedge_ratio = row["hedge_ratio"]
                entry.roll_window_flag = bool(row["roll_window_flag"])
                entry.regime = row["regime"]
                if not existing:
                    session.add(entry)

            session.commit()
            print(f"Saved {len(df)} rows for spread '{self.spread.name}'")
        finally:
            session.close()
