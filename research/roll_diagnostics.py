"""Roll-window diagnostics for commodity futures spreads.

For each spread, computes DTE (days-to-expiry) relative to the front-month roll date,
splits data into roll-window (±10 days) vs mid-cycle, runs statistical tests, and
exports a roll heatmap PNG.

CLI usage:
    uv run python research/roll_diagnostics.py [--spread wti_calendar]

Output:
    research/outputs/roll_heatmap_{spread_name}.png
    Printed stats table for copy-paste into research/notes.md
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import text

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.session import get_session

ROLL_WINDOW_DAYS = 10
OUTPUT_DIR = Path(__file__).parent / "outputs"

SPREAD_PRODUCTS = {
    "wti_calendar": "CL",
    "brent_calendar": "BZ",
    "brent_wti": "BZ",
}


def load_spread_df(session, spread_name: str) -> pd.DataFrame:
    """Load spread rows from DB as a DataFrame indexed by date."""
    rows = session.execute(
        text("""
            SELECT date, value, leg1_price, leg2_price, regime
            FROM spreads
            WHERE spread_name = :name
            ORDER BY date
        """),
        {"name": spread_name},
    ).fetchall()

    if not rows:
        raise ValueError(f"No data found for spread '{spread_name}'")

    df = pd.DataFrame(rows, columns=["date", "value", "leg1_price", "leg2_price", "regime"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df


def load_roll_dates(session, product: str) -> pd.DataFrame:
    """Load expiry dates for a product from roll_calendar."""
    rows = session.execute(
        text("""
            SELECT contract_month, expiry
            FROM roll_calendar
            WHERE product = :product
            ORDER BY expiry
        """),
        {"product": product},
    ).fetchall()
    df = pd.DataFrame(rows, columns=["contract_month", "expiry"])
    df["expiry"] = pd.to_datetime(df["expiry"])
    return df


def compute_dte_series(spread_df: pd.DataFrame, roll_df: pd.DataFrame) -> pd.Series:
    """Compute days-to-expiry for each date in spread_df.

    For each spread date, finds the nearest upcoming expiry (or most recent past expiry
    if no future expiry is within reach). Returns positive DTE = days before expiry.
    """
    expiries = roll_df["expiry"].values
    dates = spread_df.index

    dte_values = []
    for d in dates:
        d_np = np.datetime64(d, "D")
        diffs = (expiries - d_np).astype("timedelta64[D]").astype(int)
        # Prefer upcoming expiry (diffs >= 0); fallback to most recent past
        future = diffs[diffs >= 0]
        if len(future) > 0:
            dte = int(future.min())
        else:
            dte = int(diffs.max())  # most recent past (negative)
        dte_values.append(dte)

    return pd.Series(dte_values, index=dates, name="dte")


def compute_roll_window_stats(df: pd.DataFrame) -> dict:
    """Compare spread behaviour in roll window vs mid-cycle.

    Tests whether absolute daily spread changes are larger in roll windows.
    Returns dict with descriptive stats and p-values.
    """
    roll = df[df["dte"].abs() <= ROLL_WINDOW_DAYS]
    mid = df[df["dte"].abs() > ROLL_WINDOW_DAYS]

    roll_changes = roll["value"].diff().dropna().abs()
    mid_changes = mid["value"].diff().dropna().abs()

    t_stat, t_p = stats.ttest_ind(roll_changes, mid_changes, equal_var=False)
    mw_stat, mw_p = stats.mannwhitneyu(roll_changes, mid_changes, alternative="greater")

    return {
        "roll_n": len(roll),
        "mid_n": len(mid),
        "roll_spread_mean": roll["value"].mean(),
        "roll_spread_std": roll["value"].std(),
        "mid_spread_mean": mid["value"].mean(),
        "mid_spread_std": mid["value"].std(),
        "roll_daily_change_mean": roll_changes.mean(),
        "mid_daily_change_mean": mid_changes.mean(),
        "t_stat": t_stat,
        "t_p": t_p,
        "mw_stat": mw_stat,
        "mw_p": mw_p,
    }


def plot_roll_heatmap(df: pd.DataFrame, roll_df: pd.DataFrame, spread_name: str, output_dir: Path) -> None:
    """Create and save a roll heatmap PNG.

    x-axis: DTE bucket (-ROLL_WINDOW_DAYS to +ROLL_WINDOW_DAYS)
    y-axis: expiry YYYY-MM (one row per roll cycle)
    colour: mean absolute daily spread change in each (expiry, DTE) cell
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Annotate each row with expiry label (YYYY-MM) for the nearest roll
    expiries_sorted = roll_df["expiry"].sort_values().values
    expiry_labels = []
    for d in df.index:
        d_np = np.datetime64(d, "D")
        diffs = (expiries_sorted - d_np).astype("timedelta64[D]").astype(int)
        future = diffs[diffs >= 0]
        if len(future) > 0:
            nearest_expiry = expiries_sorted[np.where(diffs >= 0)[0][np.argmin(future)]]
        else:
            nearest_expiry = expiries_sorted[np.argmax(diffs)]
        expiry_labels.append(str(nearest_expiry)[:7])  # YYYY-MM
    df = df.copy()
    df["expiry_label"] = expiry_labels

    # Keep only rows within roll window
    window_df = df[df["dte"].abs() <= ROLL_WINDOW_DAYS].copy()
    window_df["abs_change"] = window_df["value"].diff().abs()

    # Pivot: rows = expiry_label, columns = dte, values = mean abs change
    pivot = window_df.pivot_table(
        index="expiry_label",
        columns="dte",
        values="abs_change",
        aggfunc="mean",
    )
    # Ensure columns span full range
    all_dte = list(range(-ROLL_WINDOW_DAYS, ROLL_WINDOW_DAYS + 1))
    pivot = pivot.reindex(columns=all_dte)

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(16, max(6, len(pivot) * 0.25)))

    im = ax.imshow(
        pivot.values,
        aspect="auto",
        cmap="YlOrRd",
        interpolation="nearest",
        vmin=0,
    )

    ax.set_xticks(range(len(all_dte)))
    ax.set_xticklabels([str(d) for d in all_dte], fontsize=7)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index, fontsize=7)
    ax.set_xlabel("Days to Expiry (DTE)", fontsize=11)
    ax.set_ylabel("Roll Cycle (Expiry Month)", fontsize=11)
    ax.set_title(f"{spread_name} - Mean |Daily Spread Change| Around Roll Window", fontsize=13)
    ax.axvline(x=ROLL_WINDOW_DAYS, color="cyan", linewidth=0.8, linestyle="--", alpha=0.7, label="Expiry")

    cbar = fig.colorbar(im, ax=ax, shrink=0.6, pad=0.02)
    cbar.set_label("Mean |ΔSpread|", fontsize=10)

    plt.tight_layout()
    out_path = output_dir / f"roll_heatmap_{spread_name}.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved heatmap → {out_path}")


def print_stats(spread_name: str, s: dict) -> None:
    """Print a formatted stats block for copy-paste into notes.md."""
    print(f"\n{'='*60}")
    print(f"  {spread_name}")
    print(f"{'='*60}")
    print(f"  Roll window (|DTE| <= {ROLL_WINDOW_DAYS}): {s['roll_n']} bars")
    print(f"  Mid-cycle:                           {s['mid_n']} bars")
    print()
    print(f"  Spread level - roll mean:  {s['roll_spread_mean']:.4f}   std: {s['roll_spread_std']:.4f}")
    print(f"  Spread level - mid  mean:  {s['mid_spread_mean']:.4f}   std: {s['mid_spread_std']:.4f}")
    print()
    print(f"  Mean |daily change| - roll: {s['roll_daily_change_mean']:.4f}")
    print(f"  Mean |daily change| - mid:  {s['mid_daily_change_mean']:.4f}")
    ratio = s['roll_daily_change_mean'] / s['mid_daily_change_mean'] if s['mid_daily_change_mean'] else float('nan')
    print(f"  Ratio (roll / mid):         {ratio:.2f}x")
    print()
    print(f"  Welch t-test (roll vol > mid vol):  t={s['t_stat']:.3f},  p={s['t_p']:.4f}")
    print(f"  Mann-Whitney U (one-sided):          U={s['mw_stat']:.0f},  p={s['mw_p']:.4f}")
    sig_t = "SIGNIFICANT" if s['t_p'] < 0.05 else "not significant"
    sig_mw = "SIGNIFICANT" if s['mw_p'] < 0.05 else "not significant"
    print(f"  → t-test: {sig_t} at α=0.05")
    print(f"  → Mann-Whitney: {sig_mw} at α=0.05")


def run_spread(session, spread_name: str) -> None:
    product = SPREAD_PRODUCTS.get(spread_name, "CL")
    print(f"\nProcessing {spread_name} (product: {product}) ...")

    spread_df = load_spread_df(session, spread_name)
    roll_df = load_roll_dates(session, product)

    dte = compute_dte_series(spread_df, roll_df)
    spread_df["dte"] = dte

    s = compute_roll_window_stats(spread_df)
    print_stats(spread_name, s)

    plot_roll_heatmap(spread_df, roll_df, spread_name, OUTPUT_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description="Roll-window diagnostics for spread series")
    parser.add_argument("--spread", help="Single spread name to process (default: all)")
    args = parser.parse_args()

    session = get_session()
    try:
        spreads = [args.spread] if args.spread else list(SPREAD_PRODUCTS.keys())
        for spread_name in spreads:
            run_spread(session, spread_name)
    finally:
        session.close()

    print("\nDone. PNGs saved to research/outputs/")


if __name__ == "__main__":
    main()
