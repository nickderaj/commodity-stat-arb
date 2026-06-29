"""Data ingestion orchestrator.

Reads all SpreadDefinition configs, routes each leg to the correct provider,
fetches 5+ years of daily OHLCV, and writes to the contracts + ohlcv_bars tables.

Usage:
    python -m data.ingest
    python -m data.ingest --start 2018-01-01 --end 2024-12-31
    python -m data.ingest --spread brent_wti          # single spread
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta

import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config.loader import load_all_spreads
from config.schema import LegConfig, SpreadDefinition
from data.providers.base import DataProvider
from data.providers.databento_provider import DatabentoPovider
from data.providers.yfinance_provider import YFinanceProvider
from data.roll_calendar import compute_expiry
from db.models import Contract, OHLCVBar
from db.session import get_session
from sqlalchemy import func

_DEFAULT_START = date(2018, 1, 1)
_DEFAULT_END = date.today()


def _latest_stored_date(
    session, product: str, exchange: str, exclude_continuous: bool = False
) -> date | None:
    """Return the most recent bar date already in the DB for this product+exchange."""
    q = (
        session.query(func.max(OHLCVBar.date))
        .join(Contract, OHLCVBar.contract_id == Contract.id)
        .filter(Contract.product == product, Contract.exchange == exchange)
    )
    if exclude_continuous:
        q = q.filter(Contract.contract_month != "continuous")
    return q.scalar()


def _get_provider(leg: LegConfig) -> DataProvider:
    if leg.provider == "yfinance":
        return YFinanceProvider()
    if leg.provider == "databento":
        return DatabentoPovider()
    raise ValueError(f"Unknown provider: {leg.provider!r}")


def _upsert_contract(session, leg: LegConfig, contract_month: str, expiry: date) -> int:
    """Insert or update a contract row; return the contract id."""
    ticker = f"{leg.ticker.replace('=F', '')}{contract_month.replace('-', '')}"
    existing = session.query(Contract).filter_by(ticker=ticker).first()
    if existing:
        existing.expiry = expiry  # keep in sync if expiry was recomputed
        return existing.id

    contract = Contract(
        ticker=ticker,
        product=leg.ticker.replace("=F", ""),
        exchange=leg.exchange,
        contract_month=contract_month,
        expiry=expiry,
    )
    session.add(contract)
    session.flush()
    return contract.id


_UPSERT_CHUNK = 500


def _upsert_bars(session, contract_id: int, df: pd.DataFrame) -> int:
    """Upsert OHLCV rows for a contract; return count of rows written."""
    if df.empty:
        return 0
    df = df[df["close"].notna()]
    # Deduplicate by date - yfinance occasionally returns duplicate rows for the same
    # date, which causes Postgres to reject the whole batch with an ON CONFLICT error.
    df = df[~df.index.duplicated(keep="last")]
    if df.empty:
        return 0

    rows = [
        {
            "contract_id": contract_id,
            "date": d,
            "open": float(row["open"]) if pd.notna(row.get("open")) else None,
            "high": float(row["high"]) if pd.notna(row.get("high")) else None,
            "low": float(row["low"]) if pd.notna(row.get("low")) else None,
            "close": float(row["close"]) if pd.notna(row.get("close")) else None,
            "volume": int(row["volume"]) if pd.notna(row.get("volume")) else None,
            "open_interest": int(row["open_interest"]) if pd.notna(row.get("open_interest")) else None,
        }
        for d, row in df.iterrows()
    ]

    total = 0
    for i in range(0, len(rows), _UPSERT_CHUNK):
        chunk = rows[i : i + _UPSERT_CHUNK]
        stmt = pg_insert(OHLCVBar.__table__).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["contract_id", "date"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "open_interest": stmt.excluded.open_interest,
            },
        )
        session.execute(stmt)
        total += len(chunk)
    return total


def ingest_spread(
    spread: SpreadDefinition,
    start: date = _DEFAULT_START,
    end: date = _DEFAULT_END,
) -> None:
    print(f"\n{'=' * 60}")
    print(f"Ingesting: {spread.display_name}")
    print(f"{'=' * 60}")

    for leg in spread.legs:
        print(f"  Leg: {leg.ticker} (provider={leg.provider}, exchange={leg.exchange})")
        provider = _get_provider(leg)
        product = leg.ticker.replace("=F", "")

        # Check what's already stored so we don't re-fetch paid data.
        # For databento legs, exclude the yfinance continuous contract so its
        # date doesn't incorrectly block individual contract-month fetches.
        check = get_session()
        try:
            latest = _latest_stored_date(
                check, product, leg.exchange,
                exclude_continuous=(leg.provider == "databento"),
            )
        finally:
            check.close()

        if latest:
            fetch_start = latest + timedelta(days=1)
            if fetch_start >= end:
                print(f"    Already up to date through {latest}, skipping")
                continue
            print(f"    Have data to {latest} - fetching {fetch_start} → {end}")
        else:
            fetch_start = start

        if leg.provider == "databento":
            try:
                bars_by_contract = provider.fetch_all_contracts(
                    product=leg.ticker,
                    exchange=leg.exchange,
                    start=fetch_start,
                    end=end,
                )
            except Exception as exc:
                print(f"    ERROR fetching {leg.ticker}: {exc}")
                print(f"    Skipping leg - check dataset access at databento.com/pricing")
                continue

            session = get_session()
            try:
                total = 0
                product_root = leg.ticker.replace("=F", "")
                for contract_month, df in bars_by_contract.items():
                    if df.empty:
                        continue
                    try:
                        expiry = compute_expiry(product_root, contract_month)
                    except (ValueError, KeyError):
                        expiry = df.index.max()
                    contract_id = _upsert_contract(session, leg, contract_month, expiry)
                    n = _upsert_bars(session, contract_id, df)
                    session.commit()  # commit per-contract so progress survives errors
                    total += n
                print(f"    Wrote {total} bars across {len(bars_by_contract)} contracts")
            except Exception as exc:
                session.rollback()
                print(f"    ERROR writing {leg.ticker} bars: {exc}")
            finally:
                session.close()

        else:
            # yfinance: single continuous ticker
            df = provider.fetch_ohlcv(leg.ticker, fetch_start, end, leg.exchange)
            if df.empty:
                print(f"    No data returned for {leg.ticker}")
                continue

            session = get_session()
            try:
                contract_month = "continuous"
                expiry = end
                contract_id = _upsert_contract(session, leg, contract_month, expiry)
                n = _upsert_bars(session, contract_id, df)
                session.commit()
                print(f"    Wrote {n} bars for {leg.ticker}")
            except Exception as exc:
                session.rollback()
                print(f"    ERROR writing {leg.ticker}: {exc}")
            finally:
                session.close()


_MONTH_CODES = "FGHJKMNQUVXZ"  # Jan–Dec


def _symbol_to_contract_month(symbol: str, product: str) -> str | None:
    """Convert a Databento contract symbol to YYYY-MM format.

    Example: "CLF4" → "2024-01", "BZG5" → "2025-02"
    The year digit is the last digit of the year; we assume 2020s.
    """
    root = product.replace("=F", "")
    suffix = symbol[len(root):]
    if len(suffix) < 2:
        return None
    month_code = suffix[0].upper()
    year_digit = suffix[1]
    if month_code not in _MONTH_CODES:
        return None
    month = _MONTH_CODES.index(month_code) + 1
    # Heuristic: year digit maps to 202X (adjust if your data spans decade boundary)
    year = 2020 + int(year_digit)
    return f"{year}-{month:02d}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest commodity futures OHLCV data")
    parser.add_argument("--start", default=str(_DEFAULT_START), help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=str(_DEFAULT_END), help="End date YYYY-MM-DD")
    parser.add_argument("--spread", default=None, help="Ingest only this spread name")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    spreads = load_all_spreads()
    if args.spread:
        spreads = [s for s in spreads if s.name == args.spread]
        if not spreads:
            print(f"Spread '{args.spread}' not found in config/")
            return

    for spread in spreads:
        ingest_spread(spread, start, end)

    print("\nIngestion complete.")


if __name__ == "__main__":
    main()
