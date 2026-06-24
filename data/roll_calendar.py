"""Roll calendar for CME WTI (CL) and ICE Brent (BZ) futures.

CME WTI (CL) rule:
    Last trading day = 3 business days before the 25th of the month
    prior to the delivery month. If the 25th is a non-business day
    (weekend OR exchange holiday), count back from the last exchange
    business day before the 25th.

ICE Brent (BZ) rule:
    Last trading day = last exchange business day of the 2nd calendar
    month before the delivery month.

Business days use a CME holiday list (US federal holidays observed by CME).
Known exceptions can be patched via MANUAL_OVERRIDES.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import numpy as np
import pandas as pd

from db.session import get_session
from db.models import RollCalendarEntry


# ─── CME holiday generation (US federal holidays observed by CME) ─────────────

def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """Return the nth occurrence of weekday (0=Mon…6=Sun) in year/month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + (n - 1) * 7)


def _nearest_weekday(d: date) -> date:
    """Observe: if Saturday → Friday, if Sunday → Monday."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _easter(year: int) -> date:
    """Compute Easter Sunday via the Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _cme_holidays(start_year: int, end_year: int) -> list[str]:
    """Return ISO-format holiday strings for all CME holidays from start_year to end_year."""
    holidays = []
    for year in range(start_year, end_year + 1):
        # New Year's Day
        holidays.append(_nearest_weekday(date(year, 1, 1)).isoformat())
        # MLK Day — 3rd Monday of January
        holidays.append(_nth_weekday_of_month(year, 1, 0, 3).isoformat())
        # Presidents' Day — 3rd Monday of February
        holidays.append(_nth_weekday_of_month(year, 2, 0, 3).isoformat())
        # Good Friday — Easter - 2 days (CME futures are closed Good Friday for most products)
        holidays.append((_easter(year) - timedelta(days=2)).isoformat())
        # Memorial Day — last Monday of May
        last_may = date(year, 5, 31)
        last_monday_may = last_may - timedelta(days=last_may.weekday())
        holidays.append(last_monday_may.isoformat())
        # Juneteenth — June 19 (observed from 2022)
        if year >= 2022:
            holidays.append(_nearest_weekday(date(year, 6, 19)).isoformat())
        # Independence Day — July 4 (observed)
        holidays.append(_nearest_weekday(date(year, 7, 4)).isoformat())
        # Labor Day — 1st Monday of September
        holidays.append(_nth_weekday_of_month(year, 9, 0, 1).isoformat())
        # Thanksgiving — 4th Thursday of November
        holidays.append(_nth_weekday_of_month(year, 11, 3, 4).isoformat())
        # Christmas — Dec 25 (observed)
        holidays.append(_nearest_weekday(date(year, 12, 25)).isoformat())

    return sorted(set(holidays))


# Build holiday array for 2015–2030 (covers our data range with buffer)
_HOLIDAYS = np.array(_cme_holidays(2015, 2030), dtype="datetime64[D]")


# ─── Manual overrides for any remaining edge cases ───────────────────────────
# Format: {(product, "YYYY-MM"): {"expiry": date(...), "first_notice_date": date(...), ...}}
MANUAL_OVERRIDES: dict[tuple[str, str], dict] = {}


# ─── Business-day helpers ─────────────────────────────────────────────────────

def _prev_biz_day(d: date) -> date:
    """Return the first CME business day on or before d."""
    arr = np.busday_offset(d.isoformat(), 0, roll="preceding", holidays=_HOLIDAYS)
    return date.fromisoformat(str(arr))


def _offset_biz_days(d: date, n: int) -> date:
    """Return date that is n CME business days before d (n > 0 = backward)."""
    arr = np.busday_offset(d.isoformat(), -n, holidays=_HOLIDAYS)
    return date.fromisoformat(str(arr))


def _last_biz_day_of_month(year: int, month: int) -> date:
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    return _prev_biz_day(last_day)


# ─── Product-specific expiry rules ───────────────────────────────────────────

def _cme_wti_expiry(delivery_year: int, delivery_month: int) -> date:
    """Last trading day for CL (WTI) with given delivery month."""
    if delivery_month == 1:
        prior_year, prior_month = delivery_year - 1, 12
    else:
        prior_year, prior_month = delivery_year, delivery_month - 1

    ref_day = date(prior_year, prior_month, 25)
    adjusted_25 = _prev_biz_day(ref_day)
    return _offset_biz_days(adjusted_25, 3)


def _ice_brent_expiry(delivery_year: int, delivery_month: int) -> date:
    """Last trading day for BZ (Brent) with given delivery month."""
    two_months_back = delivery_month - 2
    if two_months_back <= 0:
        two_months_back += 12
        ref_year = delivery_year - 1
    else:
        ref_year = delivery_year
    return _last_biz_day_of_month(ref_year, two_months_back)


_EXPIRY_FN = {
    "CL": _cme_wti_expiry,
    "BZ": _ice_brent_expiry,   # NYMEX mirror (yfinance BZ=F)
    "B": _ice_brent_expiry,    # ICE Futures Europe (Databento IFEU.IMPACT)
}


# ─── Public API ──────────────────────────────────────────────────────────────

def compute_expiry(product: str, contract_month: str) -> date:
    """Return the exchange last-trading-day for product + YYYY-MM contract month."""
    if product not in _EXPIRY_FN:
        raise ValueError(f"Unsupported product: {product!r}. Supported: {list(_EXPIRY_FN)}")
    year, month = map(int, contract_month.split("-"))
    return _EXPIRY_FN[product](year, month)


def generate_roll_calendar(
    product: str,
    start_year: int = 2018,
    end_year: int = 2027,
) -> pd.DataFrame:
    """Generate roll calendar rows for a product.

    Returns DataFrame with columns:
        product, contract_month, expiry, first_notice_date, last_trade_date.
    """
    if product not in _EXPIRY_FN:
        raise ValueError(f"Unsupported product: {product!r}. Supported: {list(_EXPIRY_FN)}")

    expiry_fn = _EXPIRY_FN[product]
    rows = []

    for year in range(start_year, end_year):
        for month in range(1, 13):
            contract_month = f"{year}-{month:02d}"
            key = (product, contract_month)
            if key in MANUAL_OVERRIDES:
                row = {"product": product, "contract_month": contract_month, **MANUAL_OVERRIDES[key]}
            else:
                expiry = expiry_fn(year, month)
                fnd = _offset_biz_days(expiry, -1) if product == "CL" else None
                row = {
                    "product": product,
                    "contract_month": contract_month,
                    "expiry": expiry,
                    "first_notice_date": fnd,
                    "last_trade_date": expiry,
                }
            rows.append(row)

    return pd.DataFrame(rows)


def seed_roll_calendar(products: list[str] | None = None) -> None:
    """Populate the roll_calendar DB table (safe to re-run, upserts)."""
    if products is None:
        products = ["CL", "BZ"]

    session = get_session()
    try:
        for product in products:
            df = generate_roll_calendar(product)
            for _, row in df.iterrows():
                month_str = row["contract_month"]
                existing = (
                    session.query(RollCalendarEntry)
                    .filter_by(product=product, contract_month=month_str)
                    .first()
                )
                if existing:
                    existing.expiry = row["expiry"]
                    existing.first_notice_date = row.get("first_notice_date")
                    existing.last_trade_date = row["last_trade_date"]
                else:
                    session.add(
                        RollCalendarEntry(
                            product=product,
                            contract_month=month_str,
                            expiry=row["expiry"],
                            first_notice_date=row.get("first_notice_date"),
                            last_trade_date=row["last_trade_date"],
                        )
                    )
        session.commit()
        print(f"Roll calendar seeded for: {products}")
    finally:
        session.close()


def get_roll_dates(product: str, start: date, end: date) -> pd.DataFrame:
    """Return roll calendar rows for a product within a date range, from DB."""
    session = get_session()
    try:
        rows = (
            session.query(RollCalendarEntry)
            .filter(
                RollCalendarEntry.product == product,
                RollCalendarEntry.expiry >= start,
                RollCalendarEntry.expiry <= end,
            )
            .order_by(RollCalendarEntry.expiry)
            .all()
        )
        return pd.DataFrame(
            [
                {
                    "product": r.product,
                    "contract_month": r.contract_month,
                    "expiry": r.expiry,
                    "first_notice_date": r.first_notice_date,
                    "last_trade_date": r.last_trade_date,
                }
                for r in rows
            ]
        )
    finally:
        session.close()


if __name__ == "__main__":
    # Print sanity check
    for prod in ["CL", "B"]:
        df = generate_roll_calendar(prod, 2023, 2025)
        print(f"\n{prod} 2024:")
        print(df[df["contract_month"].str.startswith("2024")].to_string(index=False))

    # Seed to DB — include both BZ (NYMEX mirror) and B (ICE Futures Europe)
    seed_roll_calendar(products=["CL", "BZ", "B"])
