"""Compute daily microstructure proxy metrics per contract and store in Postgres.

Metrics are OHLCV-based proxies - not true microstructure (which requires tick/intraday data).
Label them as such in any research output.

CLI usage:
    uv run python -m data.microstructure [--product CL] [--start 2018-01-01]
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import text

from db.models import Contract, ContractMetrics, OHLCVBar
from db.session import get_session


def load_all_ohlcv(
    product_filter: str | None = None,
    start: date | None = None,
) -> dict[int, pd.DataFrame]:
    """Load OHLCV bars grouped by contract_id.

    Returns dict mapping contract_id → DataFrame(date, open, high, low, close, volume, open_interest).
    """
    session = get_session()
    try:
        q = session.query(OHLCVBar, Contract).join(Contract, OHLCVBar.contract_id == Contract.id)
        if product_filter:
            q = q.filter(Contract.product == product_filter)
        if start:
            q = q.filter(OHLCVBar.date >= start)
        q = q.order_by(OHLCVBar.contract_id, OHLCVBar.date)

        by_contract: dict[int, list[dict]] = {}
        for bar, contract in q.all():
            cid = bar.contract_id
            if cid not in by_contract:
                by_contract[cid] = []
            by_contract[cid].append({
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "open_interest": bar.open_interest,
            })

        return {cid: pd.DataFrame(rows) for cid, rows in by_contract.items()}
    finally:
        session.close()


def compute_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Compute microstructure proxy metrics from an OHLCV DataFrame.

    Input columns: date, open, high, low, close, volume, open_interest.
    Returns DataFrame with: date, realised_vol_20d, hl_range_pct, avg_volume_20d, avg_oi_20d.
    NaN rows are preserved per-metric (not globally dropped) to avoid discarding early hl_range_pct.
    """
    df = df.sort_values("date").copy()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["high"] = pd.to_numeric(df["high"], errors="coerce")
    df["low"] = pd.to_numeric(df["low"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df["open_interest"] = pd.to_numeric(df["open_interest"], errors="coerce")

    log_ret = np.log(df["close"] / df["close"].shift(1))
    df["realised_vol_20d"] = log_ret.rolling(20).std() * np.sqrt(252)
    df["hl_range_pct"] = (df["high"] - df["low"]) / df["close"]
    df["avg_volume_20d"] = df["volume"].rolling(20).mean()
    df["avg_oi_20d"] = df["open_interest"].rolling(20).mean()

    return df[["date", "realised_vol_20d", "hl_range_pct", "avg_volume_20d", "avg_oi_20d"]]


def upsert_metrics(session, contract_id: int, metrics_df: pd.DataFrame) -> int:
    """Upsert computed metrics rows for a single contract.

    Returns number of rows written.
    """
    if metrics_df.empty:
        return 0

    rows = []
    for _, row in metrics_df.iterrows():
        rows.append({
            "contract_id": contract_id,
            "date": row["date"],
            "realised_vol_20d": None if pd.isna(row["realised_vol_20d"]) else float(row["realised_vol_20d"]),
            "hl_range_pct": None if pd.isna(row["hl_range_pct"]) else float(row["hl_range_pct"]),
            "avg_volume_20d": None if pd.isna(row["avg_volume_20d"]) else float(row["avg_volume_20d"]),
            "avg_oi_20d": None if pd.isna(row["avg_oi_20d"]) else float(row["avg_oi_20d"]),
        })

    chunk_size = 500
    total = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        session.execute(
            text("""
                INSERT INTO contract_metrics
                    (contract_id, date, realised_vol_20d, hl_range_pct, avg_volume_20d, avg_oi_20d)
                VALUES
                    (:contract_id, :date, :realised_vol_20d, :hl_range_pct, :avg_volume_20d, :avg_oi_20d)
                ON CONFLICT (contract_id, date) DO UPDATE SET
                    realised_vol_20d = EXCLUDED.realised_vol_20d,
                    hl_range_pct     = EXCLUDED.hl_range_pct,
                    avg_volume_20d   = EXCLUDED.avg_volume_20d,
                    avg_oi_20d       = EXCLUDED.avg_oi_20d
            """),
            chunk,
        )
        total += len(chunk)
    session.commit()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute microstructure proxy metrics per contract")
    parser.add_argument("--product", help="Filter to product code (e.g. CL, BZ)")
    parser.add_argument("--start", help="Start date YYYY-MM-DD (default 2018-01-01)", default="2018-01-01")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    product_filter = args.product

    print(f"Loading OHLCV bars (product={product_filter or 'all'}, start={start_date}) ...")
    ohlcv_by_contract = load_all_ohlcv(product_filter=product_filter, start=start_date)
    print(f"  Loaded {len(ohlcv_by_contract)} contracts")

    session = get_session()
    total_rows = 0
    try:
        for i, (contract_id, df) in enumerate(ohlcv_by_contract.items(), 1):
            metrics_df = compute_metrics(df)
            rows_saved = upsert_metrics(session, contract_id, metrics_df)
            total_rows += rows_saved
            if i % 50 == 0:
                print(f"  Processed {i}/{len(ohlcv_by_contract)} contracts ({total_rows} rows so far) ...")
    finally:
        session.close()

    print(f"Done. Saved {total_rows} metric rows for {len(ohlcv_by_contract)} contracts.")


if __name__ == "__main__":
    main()
