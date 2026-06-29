"""Carry fair-value model for commodity calendar spreads.

Computes cost-of-carry baseline (storage + financing), derives excess spread,
compares stationarity vs raw spread, plots M1-M6 term structure, and updates
ts_regime (contango / backwardation) in the spreads table.

CLI usage:
    uv run python research/carry_model.py [--product CL] [--no-plots]
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
from research.stats import compute_half_life, rolling_half_life, run_adf, run_kpss

OUTPUT_DIR = Path(__file__).parent / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Parametric storage cost range ($/bbl/month) for WTI/Brent
STORAGE_LOW = 0.30
STORAGE_HIGH = 0.60
STORAGE_MID = (STORAGE_LOW + STORAGE_HIGH) / 2  # 0.45

# Approximate financing rate (annualised), used when no real yield data loaded
FINANCING_RATE_APPROX = 0.05  # 5% SOFR-ish

CALENDAR_SPREADS = {
    "wti_calendar": "CL",
    "brent_calendar": "BZ",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_spread_df(spread_name: str) -> pd.DataFrame:
    session = get_session()
    try:
        rows = session.execute(
            text("""
                SELECT date, value, leg1_price, leg2_price, regime, roll_window_flag
                FROM spreads WHERE spread_name = :name ORDER BY date
            """),
            {"name": spread_name},
        ).fetchall()
    finally:
        session.close()

    df = pd.DataFrame(rows, columns=["date", "value", "leg1_price", "leg2_price", "regime", "roll_window_flag"])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def load_term_structure(product: str, n_months: int = 6) -> pd.DataFrame:
    """For each date, load the nearest n_months contract closes from ohlcv_bars.

    Returns wide DataFrame with columns M1..M{n_months} indexed by date.
    """
    session = get_session()
    try:
        rows = session.execute(
            text("""
                SELECT o.date, c.expiry, o.close
                FROM ohlcv_bars o
                JOIN contracts c ON o.contract_id = c.id
                WHERE c.product = :product
                  AND c.expiry >= o.date
                ORDER BY o.date, c.expiry
            """),
            {"product": product},
        ).fetchall()
    finally:
        session.close()

    raw = pd.DataFrame(rows, columns=["date", "expiry", "close"])
    raw["date"] = pd.to_datetime(raw["date"])
    raw["expiry"] = pd.to_datetime(raw["expiry"])

    # Rank contracts by expiry within each date
    raw["month_num"] = raw.groupby("date")["expiry"].rank(method="first").astype(int)
    raw = raw[raw["month_num"] <= n_months]

    pivot = raw.pivot(index="date", columns="month_num", values="close")
    pivot.columns = [f"M{c}" for c in pivot.columns]
    return pivot.sort_index()


# ---------------------------------------------------------------------------
# Carry fair-value model
# ---------------------------------------------------------------------------

def compute_carry_fv(
    leg2_price: pd.Series,
    storage_per_month: float = STORAGE_MID,
    financing_rate: float = FINANCING_RATE_APPROX,
) -> pd.Series:
    """Estimate cost-of-carry fair value for M1-M2 calendar spread.

    Fair spread (M1 - M2) in contango = -(storage + financing)
    i.e. M2 should be higher than M1 by the monthly carry cost.

    carry_fv = -(storage + financing_per_month)
    where financing_per_month = rate * M2_price / 12
    """
    financing = financing_rate * leg2_price / 12
    fv = -(storage_per_month + financing)
    return fv


def compute_excess_spread(
    spread_value: pd.Series,
    carry_fv: pd.Series,
) -> pd.Series:
    """Excess spread = observed (M1-M2) - carry fair value.

    Positive excess → more backwardated than fair value suggests (convenience yield elevated)
    Negative excess → more contangoed than fair value suggests (storage oversupply signal)
    """
    return (spread_value - carry_fv).rename("excess_spread")


def label_ts_regime(spread_value: pd.Series) -> pd.Series:
    """Contango / backwardation label from calendar spread sign.

    spread = M1 - M2
    > 0 → backwardation (M1 > M2, prompt premium)
    < 0 → contango (M1 < M2, carry/storage dominant)
    """
    return spread_value.map(lambda v: "backwardation" if v > 0 else "contango")


def save_ts_regime(spread_name: str, ts_regime: pd.Series) -> None:
    """Write ts_regime labels back to spreads table."""
    session = get_session()
    try:
        for date, regime in ts_regime.items():
            session.execute(
                text("""
                    UPDATE spreads SET ts_regime = :regime
                    WHERE spread_name = :name AND date = :date
                """),
                {"regime": regime, "name": spread_name, "date": date.date()},
            )
        session.commit()
        print(f"  Updated ts_regime for {spread_name} ({len(ts_regime)} rows)")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Stationarity comparison
# ---------------------------------------------------------------------------

def compare_stationarity(raw_spread: pd.Series, excess_spread: pd.Series) -> None:
    """Print ADF / half-life comparison: raw spread vs excess spread."""
    from research.stats import rolling_half_life, run_adf

    print("\n  Stationarity comparison (raw spread vs excess spread):")
    print(f"  {'Metric':<30} {'Raw spread':>14} {'Excess spread':>14}")
    print(f"  {'-'*60}")

    adf_raw = run_adf(raw_spread)
    adf_exc = run_adf(excess_spread)
    print(f"  {'ADF stat':<30} {adf_raw['adf_stat']:>14.4f} {adf_exc['adf_stat']:>14.4f}")
    print(f"  {'ADF p-value':<30} {adf_raw['adf_p']:>14.4f} {adf_exc['adf_p']:>14.4f}")

    hl_raw = compute_half_life(raw_spread)
    hl_exc = compute_half_life(excess_spread)
    print(f"  {'Half-life (days)':<30} {hl_raw:>14.1f} {hl_exc:>14.1f}")

    return {
        "raw": {"adf_stat": adf_raw["adf_stat"], "adf_p": adf_raw["adf_p"], "half_life": hl_raw},
        "excess": {"adf_stat": adf_exc["adf_stat"], "adf_p": adf_exc["adf_p"], "half_life": hl_exc},
    }


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def plot_excess_spread(
    df: pd.DataFrame,
    carry_fv: pd.Series,
    excess: pd.Series,
    spread_name: str,
) -> None:
    """Three-panel: raw spread + carry bounds, carry FV, excess spread."""
    plt.style.use("dark_background")
    fig, axes = plt.subplots(3, 1, figsize=(16, 11), sharex=True)
    fig.suptitle(f"{spread_name} - Carry Fair-Value Model", fontsize=13)

    # Panel 1: raw spread + carry band
    ax = axes[0]
    ax.plot(df.index, df["value"], color="#00bcd4", linewidth=0.8, label="Observed spread (M1-M2)")
    fv_low = compute_carry_fv(df["leg2_price"], STORAGE_LOW)
    fv_high = compute_carry_fv(df["leg2_price"], STORAGE_HIGH)
    ax.fill_between(df.index, fv_low, fv_high, alpha=0.25, color="#ff9800", label="Carry FV range")
    ax.plot(carry_fv.index, carry_fv.values, color="#ff9800", linewidth=0.8, linestyle="--", label="Carry FV (mid)")
    ax.axhline(0, color="white", linewidth=0.3, linestyle="--", alpha=0.4)
    ax.set_ylabel("$/bbl")
    ax.legend(fontsize=8)
    ax.set_title("Observed vs Carry Fair Value")

    # Panel 2: carry FV decomposition
    ax = axes[1]
    financing = FINANCING_RATE_APPROX * df["leg2_price"] / 12
    ax.plot(df.index, -financing, color="#4caf50", linewidth=0.8, label="Financing component (-r*M2/12)")
    ax.axhline(-STORAGE_MID, color="#f44336", linewidth=0.8, linestyle="--", label=f"Storage (-${STORAGE_MID}/bbl/mo)")
    ax.set_ylabel("$/bbl")
    ax.legend(fontsize=8)
    ax.set_title("Carry Components")

    # Panel 3: excess spread
    ax = axes[2]
    colors = excess.map(lambda v: "#4caf50" if v > 0 else "#f44336")
    ax.bar(excess.index, excess.values, color=colors, width=1, alpha=0.7)
    ax.axhline(0, color="white", linewidth=0.5)
    ax.set_ylabel("$/bbl")
    ax.set_xlabel("Date")
    ax.set_title("Excess Spread = Observed - Carry FV  (>0: more backwardated than fair)")

    plt.tight_layout()
    out = OUTPUT_DIR / f"excess_spread_{spread_name}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved excess spread chart → {out}")


def plot_term_structure(ts_df: pd.DataFrame, product: str, n_snapshots: int = 12) -> None:
    """Plot M1-M6 term structure curves as overlapping snapshots, coloured by date."""
    # Sample dates roughly every quarter
    all_dates = ts_df.dropna(thresh=4).index
    step = max(1, len(all_dates) // n_snapshots)
    sample_dates = all_dates[::step][:n_snapshots]

    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle(f"{product} Term Structure (M1-M6)", fontsize=13)

    cmap = plt.cm.plasma
    colors = [cmap(i / len(sample_dates)) for i in range(len(sample_dates))]

    for date, color in zip(sample_dates, colors):
        row = ts_df.loc[date].dropna()
        if len(row) < 3:
            continue
        months = [int(c[1:]) for c in row.index]
        ax1.plot(months, row.values, color=color, alpha=0.7, linewidth=1.2,
                 marker="o", markersize=3)

    ax1.set_xlabel("Contract month (1=front)")
    ax1.set_ylabel("Price ($/bbl)")
    ax1.set_title("Term Structure Snapshots")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0, len(sample_dates)))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax1)
    cbar.set_label("Date (early → late)")

    # Contango/backwardation regime from M1-M2 spread
    if "M1" in ts_df.columns and "M2" in ts_df.columns:
        m1_m2 = ts_df["M1"] - ts_df["M2"]
        regime = (m1_m2 > 0).resample("ME").mean()  # fraction of days in backwardation per month
        ax2.bar(regime.index, regime.values * 100, color="#ff9800", width=20, alpha=0.8)
        ax2.axhline(50, color="white", linewidth=0.5, linestyle="--", alpha=0.5)
        ax2.set_xlabel("Month")
        ax2.set_ylabel("% days in backwardation")
        ax2.set_title("Backwardation frequency by month")
        ax2.set_ylim(0, 100)

    plt.tight_layout()
    out = OUTPUT_DIR / f"term_structure_{product.lower()}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved term structure chart → {out}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Carry fair-value model for calendar spreads")
    parser.add_argument("--product", help="Single product to run (CL or BZ; default: both)")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()

    products_to_run = {
        k: v for k, v in CALENDAR_SPREADS.items()
        if args.product is None or v == args.product.upper()
    }

    results = {}

    for spread_name, product in products_to_run.items():
        print(f"\n=== {spread_name} ({product}) ===")
        df = load_spread_df(spread_name)

        # Carry fair value + excess spread
        carry_fv = compute_carry_fv(df["leg2_price"])
        excess = compute_excess_spread(df["value"], carry_fv)

        # Stationarity comparison
        stats = compare_stationarity(df["value"], excess)

        # Sensitivity: show how carry FV and excess spread change with storage cost
        print(f"\n  Storage cost sensitivity (carry FV at midpoint = ${STORAGE_MID}/bbl/mo):")
        print(f"  {'Storage ($/bbl/mo)':<25} {'FV (mean)':>12} {'Excess HL (days)':>18}")
        for stor in [STORAGE_LOW, STORAGE_MID, STORAGE_HIGH]:
            fv = compute_carry_fv(df["leg2_price"], stor)
            exc = compute_excess_spread(df["value"], fv)
            hl = compute_half_life(exc)
            print(f"  {stor:<25.2f} {fv.mean():>12.4f} {hl:>18.1f}")

        # Term structure regime labels
        ts_regime = label_ts_regime(df["value"])
        contango_pct = (ts_regime == "contango").mean()
        print(f"\n  TS regime: {contango_pct:.0%} contango, {1-contango_pct:.0%} backwardation")

        # Save to DB
        save_ts_regime(spread_name, ts_regime)

        # Term structure curves
        print(f"  Loading term structure for {product} ...")
        ts_df = load_term_structure(product, n_months=6)
        print(f"  Term structure: {len(ts_df)} dates, columns={list(ts_df.columns)}")

        if not args.no_plots:
            plot_excess_spread(df, carry_fv, excess, spread_name)
            plot_term_structure(ts_df, product)

        results[spread_name] = {
            "carry_fv_mean": float(carry_fv.mean()),
            "excess_hl": float(compute_half_life(excess)),
            "raw_hl": float(compute_half_life(df["value"])),
            "contango_pct": float(contango_pct),
            "excess_adf_p": stats["excess"]["adf_p"],
            "raw_adf_p": stats["raw"]["adf_p"],
        }

    print("\n=== SUMMARY ===")
    for name, r in results.items():
        print(f"{name}: carry_fv_mean={r['carry_fv_mean']:.3f}, "
              f"raw_hl={r['raw_hl']:.1f}d vs excess_hl={r['excess_hl']:.1f}d  "
              f"(raw adf_p={r['raw_adf_p']:.4f}, excess adf_p={r['excess_adf_p']:.4f})")

    return results


if __name__ == "__main__":
    main()
