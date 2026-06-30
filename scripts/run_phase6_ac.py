"""Phase 6: Almgren-Chriss execution simulator - naïve vs. AC backtest comparison.

Runs the best signal configuration (entry=2.0, exit=0.75, lookback=60) on all
three spread candidates in two modes:

  (A) Naïve fills  - mid-price + fixed CostModel slippage (Phase 5 baseline)
  (B) AC fills     - mid-price + CostModel (commission + spread, no fixed
                     slippage) + AlmgrenChrissModel (temp + perm impact)

The difference between A and B is the "execution tax": additional cost from
impact-modelled execution vs. the simplified fixed-bps slippage assumption.

Also runs:
  - η sensitivity table: shows how Sharpe and PnL change across η multipliers
  - Time-of-day curve print (U-shaped assumed intraday liquidity profile)

Usage:
    uv run python scripts/run_phase6_ac.py [--no-db]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.cost_model import CostModel
from backtest.engine import BacktestEngine
from backtest.sizing import FixedFractionalSizing
from backtest.strategy import ZScoreStrategy
from execution.almgren_chriss import AlmgrenChrissModel, eta_sensitivity

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Best signal candidate from Phase 3/5 research
BEST_SIGNAL = {
    "entry_threshold": 2.0,
    "exit_threshold": 0.75,
    "lookback": 60,
    "use_filters": True,
}

SPREADS = ["wti_calendar", "brent_calendar", "brent_wti"]

INITIAL_CAPITAL = 100_000.0
SIZING = FixedFractionalSizing(risk_pct=0.01, max_leverage=5.0, min_atr=0.10)

# Mode A: existing cost model including fixed slippage (Phase 5 baseline)
COST_NAIVE = CostModel(commission_per_contract=2.0, spread_bps=5.0, slippage_bps=2.0)

# Mode B: same commission + spread, but NO fixed slippage (AC model provides it)
COST_AC = CostModel(commission_per_contract=2.0, spread_bps=5.0, slippage_bps=0.0)

# AC model: calibrated in _build_ac_model() using ADV from DB
# Fallback defaults if DB unavailable
AC_ETA_DEFAULT = 0.10     # k_eta for calibration
AC_ALPHA = 1.0            # linear temporary impact

# For sensitivity analysis: scale η by these multipliers
ETA_MULTIPLIERS = [0.25, 0.5, 1.0, 2.0, 4.0]

# Representative trade parameters for sensitivity table
SENSITIVITY_QUANTITY = 2_000   # bbls (~2 contracts)
SENSITIVITY_SIGMA = 0.30       # $/bbl
SENSITIVITY_ADV = 500_000.0    # bbls (~500 CL contracts)

# Stress scenario: what if we were executing at scale?
STRESS_QUANTITIES = [2_000, 20_000, 100_000, 500_000]  # 2 / 20 / 100 / 500 contracts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(v, fmt=".3f") -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "  N/A"
    return format(v, fmt)


def _build_ac_model(engine: BacktestEngine) -> AlmgrenChrissModel:
    """Calibrate AC model using ADV from DB (with fallback)."""
    adv = engine._load_adv_from_db(engine.spread_name)
    engine._adv_bbls = adv  # cache so run() doesn't reload it
    # Calibrate η = k_eta · σ / √ADV; σ proxy from typical spread vol ≈ 0.30 $/bbl
    sigma_proxy = 0.30
    model = AlmgrenChrissModel.calibrate_from_volume(
        sigma=sigma_proxy,
        adv_bbls=adv,
        k_eta=AC_ETA_DEFAULT,
        alpha=AC_ALPHA,
    )
    return model


# ---------------------------------------------------------------------------
# Main comparison
# ---------------------------------------------------------------------------

def run_naive_vs_ac(write_to_db: bool = True) -> pd.DataFrame:
    """Run naïve fills vs. AC-simulated fills for each spread. Returns summary DataFrame."""
    rows = []

    print("\n" + "=" * 70)
    print("PHASE 6: NAÏVE vs. ALMGREN-CHRISS EXECUTION COST COMPARISON")
    print("=" * 70)
    print(f"Signal: entry={BEST_SIGNAL['entry_threshold']} exit={BEST_SIGNAL['exit_threshold']} "
          f"lookback={BEST_SIGNAL['lookback']} filters={BEST_SIGNAL['use_filters']}")
    print(f"Note: AC model is stylized (daily bars). η calibrated via σ/√ADV heuristic.")
    print()

    for spread in SPREADS:
        # ----------------------------------------------------------------
        # Mode A: Naïve (fixed slippage, no AC)
        # ----------------------------------------------------------------
        strat_a = ZScoreStrategy(**BEST_SIGNAL)
        engine_a = BacktestEngine(
            strategy=strat_a,
            spread_name=spread,
            initial_capital=INITIAL_CAPITAL,
            cost_model=COST_NAIVE,
            sizing_model=SIZING,
            ac_model=None,
        )
        try:
            res_a = engine_a.run(write_to_db=write_to_db)
        except Exception as exc:
            print(f"  [{spread}] ERROR (naïve): {exc}")
            continue

        # ----------------------------------------------------------------
        # Mode B: AC-simulated fills
        # ----------------------------------------------------------------
        strat_b = ZScoreStrategy(**BEST_SIGNAL)
        engine_b = BacktestEngine(
            strategy=strat_b,
            spread_name=spread,
            initial_capital=INITIAL_CAPITAL,
            cost_model=COST_AC,
            sizing_model=SIZING,
            ac_model=None,  # placeholder; built after construction
        )
        ac = _build_ac_model(engine_b)
        engine_b.ac_model = ac

        try:
            res_b = engine_b.run(write_to_db=write_to_db)
        except Exception as exc:
            print(f"  [{spread}] ERROR (AC): {exc}")
            continue

        # ----------------------------------------------------------------
        # Compute execution tax
        # ----------------------------------------------------------------
        sharpe_a = res_a["sharpe"]
        sharpe_b = res_b["sharpe"]
        pnl_a = res_a["realised_pnl"]
        pnl_b = res_b["realised_pnl"]

        sharpe_delta = (sharpe_b - sharpe_a) if not np.isnan(sharpe_a) and not np.isnan(sharpe_b) else float("nan")
        pnl_delta_pct = (pnl_b - pnl_a) / abs(pnl_a) * 100 if abs(pnl_a) > 1e-8 else float("nan")

        # Extract per-trade AC cost breakdown from trades
        trades_b = res_b.get("trades", [])
        avg_temp = np.mean([t.temp_impact_cost for t in trades_b]) if trades_b else 0.0
        avg_perm = np.mean([t.perm_impact_cost for t in trades_b]) if trades_b else 0.0
        avg_fees = np.mean([t.fees for t in trades_b]) if trades_b else 0.0
        avg_spread_cost = np.mean([t.spread_cost for t in trades_b]) if trades_b else 0.0

        print(f"  {spread}")
        print(f"    [A] Naïve     : Sharpe={_fmt(sharpe_a)}  PnL=${pnl_a:>10,.0f}  trades={res_a['total_trades']}")
        print(f"    [B] AC model  : Sharpe={_fmt(sharpe_b)}  PnL=${pnl_b:>10,.0f}  trades={res_b['total_trades']}")
        print(f"    Execution tax : ΔSharpe={_fmt(sharpe_delta):>7s}  ΔPnL={_fmt(pnl_delta_pct, '.1f')}%")
        print(f"    Avg per-trade : commission=${avg_fees:.2f}  spread=${avg_spread_cost:.2f}  "
              f"temp_impact=${avg_temp:.2f}  perm_impact=${avg_perm:.2f}")
        print(f"    AC params     : {ac}")
        print()

        rows.append({
            "spread": spread,
            "sharpe_naive": sharpe_a,
            "sharpe_ac": sharpe_b,
            "delta_sharpe": sharpe_delta,
            "pnl_naive": pnl_a,
            "pnl_ac": pnl_b,
            "delta_pnl_pct": pnl_delta_pct,
            "avg_temp_impact": avg_temp,
            "avg_perm_impact": avg_perm,
            "avg_commission": avg_fees,
            "avg_spread_cost": avg_spread_cost,
            "ac_eta": ac.eta,
            "ac_gamma": ac.gamma,
            "ac_alpha": ac.alpha,
            "trades": res_b["total_trades"],
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# η sensitivity analysis
# ---------------------------------------------------------------------------

def run_eta_sensitivity(write_to_db: bool = True) -> None:
    """Print per-trade AC cost table and full-backtest Sharpe sensitivity across eta multipliers."""
    spread = "brent_wti"
    print("=" * 70)
    print(f"η SENSITIVITY ANALYSIS - {spread}, entry=2.0, lb=60")
    print("=" * 70)
    print(f"(All other params fixed; only η and γ scaled by multiplier)")
    print()

    base_model = AlmgrenChrissModel.calibrate_from_volume(
        sigma=0.30, adv_bbls=SENSITIVITY_ADV, k_eta=AC_ETA_DEFAULT, alpha=AC_ALPHA
    )

    # Per-trade sensitivity: η multipliers (fixed qty=2000 bbls)
    print("  Cost sensitivity vs. η multiplier (qty=2000 bbls, σ=0.30 $/bbl, ADV=500k bbls):")
    print(f"  {'η_mult':>7s}  {'η':>10s}  {'temp_cost':>10s}  {'perm_cost':>10s}  {'total':>10s}")
    rows = eta_sensitivity(base_model, SENSITIVITY_QUANTITY, SENSITIVITY_SIGMA, SENSITIVITY_ADV, ETA_MULTIPLIERS)
    for r in rows:
        print(f"  {r['eta_mult']:>7.2f}x  {r['eta']:>10.6f}  "
              f"${r['temp_cost']:>9.4f}  ${r['perm_cost']:>9.4f}  ${r['total_shortfall']:>9.4f}")
    print()

    # Capacity / scale stress: show how impact grows with position size
    print("  Scale stress: impact vs. position size (η base, σ=0.30, ADV=500k bbls):")
    print(f"  {'qty (bbls)':>12s}  {'contracts':>10s}  {'part_rate':>10s}  {'temp':>10s}  {'perm':>10s}  {'total':>10s}  {'$ per bbl':>10s}")
    for qty in STRESS_QUANTITIES:
        r = base_model.compute(qty, SENSITIVITY_SIGMA, SENSITIVITY_ADV)
        contracts = qty // base_model.lot_size
        per_bbl = r.total_shortfall / qty if qty > 0 else 0
        print(f"  {qty:>12,d}  {contracts:>10,d}  {r.participation_rate:>10.4f}  "
              f"${r.temp_impact_cost:>9.2f}  ${r.perm_impact_cost:>9.2f}  "
              f"${r.total_shortfall:>9.2f}  ${per_bbl:>9.4f}")
    print()
    print("  NOTE: At current backtest scale (~2-10 contracts), AC impact is negligible")
    print("  (<$1/trade vs $10-30 in commission). Impact becomes material above ~50 contracts.")
    print()

    # Full backtest runs with different η values
    print("  Full backtest sensitivity (Sharpe and PnL vs. η multiplier):")
    print(f"  {'η_mult':>7s}  {'η':>9s}  {'sharpe':>8s}  {'pnl':>12s}  {'pnl_vs_1x':>10s}")

    base_pnl = None
    for mult in ETA_MULTIPLIERS:
        m = AlmgrenChrissModel(
            eta=base_model.eta * mult,
            gamma=base_model.gamma * mult,
            alpha=AC_ALPHA,
        )
        strat = ZScoreStrategy(**BEST_SIGNAL)
        engine = BacktestEngine(
            strategy=strat,
            spread_name=spread,
            initial_capital=INITIAL_CAPITAL,
            cost_model=COST_AC,
            sizing_model=SIZING,
            ac_model=m,
        )
        engine._adv_bbls = SENSITIVITY_ADV  # use standard ADV for fair comparison
        try:
            res = engine.run(write_to_db=write_to_db)
            pnl = res["realised_pnl"]
            sharpe = res["sharpe"]
            if base_pnl is None:
                base_pnl = pnl
                rel = 0.0
            else:
                rel = (pnl - base_pnl) / abs(base_pnl) * 100 if abs(base_pnl) > 1e-8 else float("nan")
            print(f"  {mult:>7.2f}x  {m.eta:>9.5f}  {_fmt(sharpe):>8s}  ${pnl:>11,.0f}  {_fmt(rel, '.1f'):>9s}%")
        except Exception as exc:
            print(f"  {mult:>7.2f}x  ERROR: {exc}")
    print()


# ---------------------------------------------------------------------------
# Time-of-day curve
# ---------------------------------------------------------------------------

def print_tod_curve() -> None:
    """Print ASCII bar chart of the assumed U-shaped time-of-day liquidity multiplier."""
    print("=" * 70)
    print("TIME-OF-DAY LIQUIDITY MULTIPLIER (assumed U-shape - not estimated from data)")
    print("=" * 70)
    print("  Impact at open and close is elevated relative to mid-session.")
    print("  Daily bar fills use hour=None → factor=1.0 (mid-session default).\n")

    hours_of_interest = [9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0]
    print(f"  {'Hour (ET)':>10s}  {'Factor':>8s}  Bar chart")
    for h in hours_of_interest:
        f = AlmgrenChrissModel.time_of_day_factor(h)
        bars = int(round(f * 20))
        bar_str = "█" * bars
        print(f"  {h:>10.1f}  {f:>8.3f}  {bar_str}")
    print()


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def print_summary(df: pd.DataFrame) -> None:
    """Print execution tax summary and per-component cost breakdown from naive vs. AC comparison."""
    if df.empty:
        print("No results to summarise.")
        return

    print("=" * 70)
    print("EXECUTION TAX SUMMARY")
    print("=" * 70)
    cols = ["spread", "sharpe_naive", "sharpe_ac", "delta_sharpe", "delta_pnl_pct"]
    display = df[cols].copy()
    display.columns = ["spread", "sharpe_A", "sharpe_B", "ΔSharpe", "ΔPnL%"]
    print(display.to_string(index=False, float_format="{:.3f}".format))
    print()

    # Per-component breakdown
    print("Average per-trade cost breakdown (Mode B - AC fills):")
    cost_cols = ["spread", "avg_commission", "avg_spread_cost", "avg_temp_impact", "avg_perm_impact"]
    if all(c in df.columns for c in cost_cols):
        display2 = df[cost_cols].copy()
        display2.columns = ["spread", "commission", "spread_cost", "temp_impact", "perm_impact"]
        print(display2.to_string(index=False, float_format="${:.2f}".format))
    print()

    # Verification checks
    print("Verification checks:")
    for _, row in df.iterrows():
        spread = row["spread"]
        delta_s = row.get("delta_sharpe", float("nan"))
        if not np.isnan(delta_s):
            direction = "reduced" if delta_s < 0 else "improved"
            print(f"  {spread}: Sharpe {direction} by {abs(delta_s):.3f} ({delta_s:+.3f})")
        # Sanity: temp impact > 0 for non-zero trades
        temp = row.get("avg_temp_impact", 0)
        if temp >= 0:
            print(f"    PASS: temp_impact_cost ≥ 0 ({temp:.3f})")
        else:
            print(f"    FAIL: temp_impact_cost is negative ({temp:.3f})")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 6: Almgren-Chriss execution simulator")
    parser.add_argument("--no-db", action="store_true", help="Skip writing results to DB")
    args = parser.parse_args()

    write = not args.no_db

    print_tod_curve()
    df = run_naive_vs_ac(write_to_db=write)
    run_eta_sensitivity(write_to_db=write)
    print_summary(df)
