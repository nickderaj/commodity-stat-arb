"""Z-score mean-reversion signal engine with regime filters.

Computes rolling z-score signals on each spread, applies optional regime filters
(roll-window vol, volatility regime, liquidity), runs a simplified vectorized
backtest across all parameter combinations, and produces Sharpe heatmaps.

This is a RESEARCH-phase parameter scan - no transaction costs yet (Phase 5).
The point is candidate selection and ridge identification, not exact Sharpe numbers.

CLI usage:
    uv run python research/signals.py [--spread wti_calendar] [--no-plots]
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sqlalchemy import text

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.session import get_session

OUTPUT_DIR = Path(__file__).parent / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SPREADS = ["wti_calendar", "brent_calendar", "brent_wti"]

ENTRY_THRESHOLDS = [1.0, 1.5, 2.0]
EXIT_THRESHOLDS = [0.3, 0.5, 0.75]
LOOKBACKS = [20, 30, 60]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_spread_df(spread_name: str) -> pd.DataFrame:
    """Load spread from DB: date, value, leg1_price, leg2_price, regime, roll_window_flag."""
    session = get_session()
    try:
        rows = session.execute(
            text("""
                SELECT date, value, leg1_price, leg2_price, regime, roll_window_flag
                FROM spreads
                WHERE spread_name = :name
                ORDER BY date
            """),
            {"name": spread_name},
        ).fetchall()
    finally:
        session.close()

    if not rows:
        raise ValueError(f"No data for spread '{spread_name}'")

    df = pd.DataFrame(rows, columns=["date", "value", "leg1_price", "leg2_price", "regime", "roll_window_flag"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def load_front_month_volume(product: str) -> pd.Series:
    """Load front-month avg_volume_20d from contract_metrics for each date."""
    session = get_session()
    try:
        rows = session.execute(
            text("""
                SELECT DISTINCT ON (cm.date)
                    cm.date,
                    cm.avg_volume_20d
                FROM contract_metrics cm
                JOIN contracts c ON cm.contract_id = c.id
                WHERE c.product = :product
                  AND c.expiry >= cm.date
                ORDER BY cm.date, c.expiry ASC
            """),
            {"product": product},
        ).fetchall()
    finally:
        session.close()

    if not rows:
        return pd.Series(dtype=float)

    s = pd.Series(
        {pd.Timestamp(r[0]): r[1] for r in rows},
        name=f"{product}_volume",
    )
    return s.sort_index()


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------

def compute_zscore(spread: pd.Series, lookback: int) -> pd.Series:
    """Rolling z-score: (spread - rolling_mean) / rolling_std, shift(1) for no look-ahead."""
    mu = spread.rolling(lookback, min_periods=lookback // 2).mean()
    sigma = spread.rolling(lookback, min_periods=lookback // 2).std()
    z = (spread - mu) / sigma.replace(0, np.nan)
    # shift(1): signal at bar t uses data up through t-1 (executes at t's open/close)
    return z.shift(1)


def compute_filter_masks(
    df: pd.DataFrame,
    volume: pd.Series | None = None,
) -> pd.DataFrame:
    """Compute per-bar filter suppression masks.

    Returns DataFrame with columns:
      roll_vol_suppress  - roll window AND vol > 75th pct → suppress new entries
      vol_regime_suppress - overall vol > 90th pct → suppress
      liquidity_suppress  - volume < 10th pct → suppress (None if no volume data)
    """
    spread = df["value"]
    vol_20d = spread.diff().rolling(20, min_periods=10).std()
    # Rolling percentile within a 252-day window
    vol_pct = vol_20d.rolling(252, min_periods=60).rank(pct=True)

    roll_vol = (df["regime"] == "roll_window") & (vol_pct > 0.75)
    vol_regime = vol_pct > 0.90

    liq = pd.Series(False, index=df.index)
    if volume is not None:
        vol_aligned = volume.reindex(df.index, method="ffill")
        vol_pct_liq = vol_aligned.rolling(252, min_periods=60).rank(pct=True)
        liq = vol_pct_liq < 0.10

    return pd.DataFrame({
        "roll_vol_suppress": roll_vol,
        "vol_regime_suppress": vol_regime,
        "liquidity_suppress": liq,
        "any_suppress": roll_vol | vol_regime | liq,
    }, index=df.index)


# ---------------------------------------------------------------------------
# Simplified vectorized backtest
# ---------------------------------------------------------------------------

def run_backtest(
    zscore: pd.Series,
    spread: pd.Series,
    entry: float,
    exit_thresh: float,
    suppress: pd.Series | None = None,
) -> dict:
    """Bar-by-bar backtest on a z-score signal.

    Position rules:
      - Flat → Short spread when z > +entry (expect reversion down)
      - Flat → Long spread when z < -entry  (expect reversion up)
      - Exit when |z| < exit_thresh
      - suppress (boolean Series): blocks NEW entries on that bar

    PnL at bar t = position[t-1] × (spread[t] - spread[t-1])
    No costs (Phase 5 concern).
    """
    n = len(zscore)
    position = np.zeros(n)
    in_pos = 0

    sup_arr = suppress.values if suppress is not None else None
    z_arr = zscore.values
    sp_arr = spread.values

    for i in range(1, n):
        z = z_arr[i]
        if np.isnan(z):
            position[i] = in_pos
            continue

        if in_pos == 0:
            blocked = sup_arr is not None and sup_arr[i]
            if not blocked:
                if z > entry:
                    in_pos = -1
                elif z < -entry:
                    in_pos = 1
        else:
            if abs(z) < exit_thresh:
                in_pos = 0

        position[i] = in_pos

    pos_s = pd.Series(position, index=spread.index)
    daily_change = spread.diff()
    # pnl[t] = position held at end of t-1 × change from t-1 to t
    pnl = pos_s.shift(1) * daily_change

    pnl_clean = pnl.dropna()
    if len(pnl_clean) < 20 or pnl_clean.std() < 1e-10:
        return {"sharpe": np.nan, "n_trades": 0, "total_pnl": np.nan, "win_rate": np.nan}

    # Count trade entries
    pos_changes = pos_s.diff().abs()
    n_entries = int((pos_changes > 0.5).sum()) // 2 + 1

    sharpe = float(np.sqrt(252) * pnl_clean.mean() / pnl_clean.std())
    total_pnl = float(pnl_clean.sum())
    traded_bars = pnl_clean[pnl_clean != 0]
    win_rate = float((traded_bars > 0).mean()) if len(traded_bars) > 0 else np.nan

    return {
        "sharpe": sharpe,
        "n_trades": n_entries,
        "total_pnl": total_pnl,
        "win_rate": win_rate,
    }


# ---------------------------------------------------------------------------
# Parameter scan
# ---------------------------------------------------------------------------

def param_scan(
    spread_name: str,
    df: pd.DataFrame,
    volume: pd.Series | None = None,
) -> pd.DataFrame:
    """Run all parameter combinations. Returns DataFrame of results."""
    spread = df["value"]
    filters_df = compute_filter_masks(df, volume=volume)
    suppress_all = filters_df["any_suppress"]

    results = []
    for lookback in LOOKBACKS:
        z = compute_zscore(spread, lookback)
        for entry in ENTRY_THRESHOLDS:
            for exit_thresh in EXIT_THRESHOLDS:
                for filters_on in [False, True]:
                    sup = suppress_all if filters_on else None
                    stats = run_backtest(z, spread, entry, exit_thresh, suppress=sup)
                    results.append({
                        "spread": spread_name,
                        "lookback": lookback,
                        "entry": entry,
                        "exit": exit_thresh,
                        "filters": filters_on,
                        **stats,
                    })

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def plot_heatmaps(scan_df: pd.DataFrame, spread_name: str) -> None:
    """2D Sharpe heatmap: entry_threshold × lookback, best exit_thresh per cell.

    Two panels: filters off (left) and filters on (right).
    """
    plt.style.use("dark_background")
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle(f"{spread_name} - Sharpe vs (Entry Threshold, Lookback)", fontsize=13)

    for ax, filters_on in zip(axes, [False, True]):
        sub = scan_df[scan_df["filters"] == filters_on]
        # Best exit threshold per (entry, lookback) cell
        best = sub.groupby(["entry", "lookback"])["sharpe"].max().reset_index()
        pivot = best.pivot(index="entry", columns="lookback", values="sharpe")

        vmax = max(abs(pivot.values[np.isfinite(pivot.values)]).max(), 0.01) if np.isfinite(pivot.values).any() else 1.0
        im = ax.imshow(
            pivot.values,
            aspect="auto",
            cmap="RdYlGn",
            vmin=-vmax,
            vmax=vmax,
            interpolation="nearest",
        )
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels([f"{c}d" for c in pivot.columns], fontsize=10)
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([f"|z|>{v}" for v in pivot.index], fontsize=10)
        ax.set_xlabel("Lookback window", fontsize=11)
        ax.set_ylabel("Entry threshold", fontsize=11)
        ax.set_title(f"Filters {'ON' if filters_on else 'OFF'}", fontsize=11)

        # Annotate cells
        for r in range(len(pivot.index)):
            for c in range(len(pivot.columns)):
                val = pivot.values[r, c]
                if np.isfinite(val):
                    ax.text(c, r, f"{val:.2f}", ha="center", va="center",
                            fontsize=9, color="black" if abs(val) > vmax * 0.5 else "white")

        fig.colorbar(im, ax=ax, shrink=0.8)

    plt.tight_layout()
    out = OUTPUT_DIR / f"param_scan_{spread_name}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved heatmap → {out}")


def plot_zscore_chart(df: pd.DataFrame, spread_name: str, lookback: int = 30) -> None:
    """Plot spread with z-score and regime shading for the top lookback."""
    spread = df["value"]
    z = compute_zscore(spread, lookback)

    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 8), sharex=True)
    fig.suptitle(f"{spread_name} - Spread and Z-score (lookback={lookback}d)", fontsize=13)

    # Shade roll windows
    roll_mask = df["regime"] == "roll_window"
    ax1.fill_between(df.index, df["value"].min() - 1, df["value"].max() + 1,
                     where=roll_mask.values, alpha=0.12, color="yellow", label="Roll window")

    ax1.plot(spread.index, spread.values, color="#00bcd4", linewidth=0.8)
    ax1.axhline(0, color="white", linewidth=0.3, linestyle="--", alpha=0.4)
    ax1.set_ylabel("Spread ($/bbl)")
    ax1.set_title("Spread Value")

    ax2.plot(z.index, z.values, color="#ff9800", linewidth=0.8)
    for thresh, col in [(1.5, "#4caf50"), (2.0, "#f44336")]:
        ax2.axhline(thresh, color=col, linewidth=0.6, linestyle="--", alpha=0.7, label=f"±{thresh}")
        ax2.axhline(-thresh, color=col, linewidth=0.6, linestyle="--", alpha=0.7)
    ax2.axhline(0, color="white", linewidth=0.3, linestyle="--", alpha=0.4)
    ax2.set_ylabel("Z-score")
    ax2.set_xlabel("Date")
    ax2.legend(fontsize=8)
    ax2.set_title(f"Z-score ({lookback}d rolling)")

    plt.tight_layout()
    out = OUTPUT_DIR / f"zscore_{spread_name}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved z-score chart → {out}")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_top_candidates(all_results: pd.DataFrame, top_n: int = 3) -> pd.DataFrame:
    """Print and return the best parameter combo per spread (filters on), sorted by Sharpe."""
    filtered = all_results[all_results["filters"] == True].copy()
    # Best combo per spread
    best_per_spread = (
        filtered.sort_values("sharpe", ascending=False)
        .groupby("spread", sort=False)
        .first()
        .reset_index()
        .sort_values("sharpe", ascending=False)
        .head(top_n)
    )

    print("\n=== TOP SIGNAL CANDIDATES (filters ON, best per spread) ===")
    print(f"{'Spread':<22} {'Lookback':>8} {'Entry':>6} {'Exit':>6} {'Sharpe':>8} {'Trades':>7} {'WinRate':>8}")
    print("-" * 70)
    for _, r in best_per_spread.iterrows():
        wr = f"{r['win_rate']:.0%}" if not np.isnan(r["win_rate"]) else "N/A"
        print(f"{r['spread']:<22} {r['lookback']:>8}d {r['entry']:>6.1f} {r['exit']:>6.2f} "
              f"{r['sharpe']:>8.3f} {r['n_trades']:>7} {wr:>8}")
    return best_per_spread


def load_ts_regime(spread_name: str) -> pd.Series:
    """Load ts_regime column for a spread from DB."""
    session = get_session()
    try:
        rows = session.execute(
            text("SELECT date, ts_regime FROM spreads WHERE spread_name = :name ORDER BY date"),
            {"name": spread_name},
        ).fetchall()
    finally:
        session.close()
    if not rows:
        return pd.Series(dtype=str)
    s = pd.Series({pd.Timestamp(r[0]): r[1] for r in rows}, name="ts_regime")
    return s.sort_index()


def print_regime_stratification(all_results: pd.DataFrame, all_dfs: dict) -> None:
    """Print Sharpe by term-structure regime for top param combo per spread."""
    print("\n=== PERFORMANCE BY TS REGIME (calendar spreads only) ===")
    for spread_name, df in all_dfs.items():
        if spread_name == "brent_wti":
            continue  # no ts_regime for cross-market spread
        ts_regime = load_ts_regime(spread_name)
        if ts_regime.empty:
            continue

        best = (
            all_results[(all_results["spread"] == spread_name) & (all_results["filters"] == True)]
            .sort_values("sharpe", ascending=False)
            .iloc[0]
        )
        lookback, entry, exit_t = int(best["lookback"]), float(best["entry"]), float(best["exit"])
        z = compute_zscore(df["value"], lookback)

        print(f"  {spread_name} (best: lookback={lookback}d entry={entry} exit={exit_t})")
        for regime in ["contango", "backwardation"]:
            mask = ts_regime == regime
            mask = mask.reindex(df.index, fill_value=False)
            if mask.sum() < 50:
                continue
            # Run on the full series but only count PnL during this regime's periods
            pos_full = _compute_position_series(z, df["value"], entry, exit_t, suppress=None)
            daily_change = df["value"].diff()
            pnl = pos_full.shift(1) * daily_change
            pnl_regime = pnl[mask].dropna()
            if len(pnl_regime) < 10 or pnl_regime.std() < 1e-10:
                print(f"    {regime:<15} insufficient data")
                continue
            sharpe = float(np.sqrt(252) * pnl_regime.mean() / pnl_regime.std())
            n_days = int(mask.sum())
            print(f"    {regime:<15} Sharpe={sharpe:.3f}  regime_days={n_days}  pnl=${pnl_regime.sum():.2f}/bbl")


def _compute_position_series(
    zscore: pd.Series, spread: pd.Series, entry: float, exit_thresh: float,
    suppress: pd.Series | None = None
) -> pd.Series:
    """Helper: run backtest loop and return full position Series."""
    n = len(zscore)
    position = np.zeros(n)
    in_pos = 0
    sup_arr = suppress.values if suppress is not None else None
    z_arr = zscore.values

    for i in range(1, n):
        z = z_arr[i]
        if np.isnan(z):
            position[i] = in_pos
            continue
        if in_pos == 0:
            blocked = sup_arr is not None and sup_arr[i]
            if not blocked:
                if z > entry:
                    in_pos = -1
                elif z < -entry:
                    in_pos = 1
        else:
            if abs(z) < exit_thresh:
                in_pos = 0
        position[i] = in_pos

    return pd.Series(position, index=spread.index)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Z-score signal parameter scan")
    parser.add_argument("--spread", help="Single spread to run (default: all)")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()

    spreads = [args.spread] if args.spread else SPREADS
    all_results = []
    all_dfs = {}

    # Volume data (only for DB-backed calendar spreads)
    volume_map = {
        "wti_calendar": load_front_month_volume("CL"),
        "brent_calendar": load_front_month_volume("BZ"),
        "brent_wti": None,
    }

    for spread_name in spreads:
        print(f"\nProcessing {spread_name} ...")
        df = load_spread_df(spread_name)
        all_dfs[spread_name] = df
        volume = volume_map.get(spread_name)
        results = param_scan(spread_name, df, volume=volume)
        all_results.append(results)

        # Print summary table for this spread
        best_nofilter = results[results["filters"] == False].sort_values("sharpe", ascending=False).head(3)
        best_filter = results[results["filters"] == True].sort_values("sharpe", ascending=False).head(3)
        print(f"  Top 3 (no filter): {list(zip(best_nofilter['lookback'], best_nofilter['entry'], best_nofilter['sharpe'].round(3)))}")
        print(f"  Top 3 (filtered):  {list(zip(best_filter['lookback'], best_filter['entry'], best_filter['sharpe'].round(3)))}")

        if not args.no_plots:
            plot_heatmaps(results, spread_name)
            plot_zscore_chart(df, spread_name, lookback=30)

    combined = pd.concat(all_results, ignore_index=True)
    top = print_top_candidates(combined)
    print_regime_stratification(combined, all_dfs)

    # Save results CSV
    out_csv = OUTPUT_DIR / "param_scan_results.csv"
    combined.to_csv(out_csv, index=False)
    print(f"\nFull results saved to {out_csv}")

    return combined, all_dfs


if __name__ == "__main__":
    main()
