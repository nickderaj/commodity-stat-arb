"""Phase 5 full backtest sweep: all spreads x 2 sizing methods x top signal params.

Runs the event-driven engine with the CostModel and both sizing methods across
all configured spread candidates. Each unique (spread, signal params, cost params,
sizing params) combination gets one row in backtest_runs with a deterministic hash
- re-running is idempotent.

Prints a ranked summary table of runs sorted by Sharpe ratio.

Usage:
    uv run python scripts/run_phase5_sweep.py [--no-db]
"""

from __future__ import annotations

import argparse
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.cost_model import CostModel
from backtest.engine import BacktestEngine
from backtest.sizing import ATRSizing, FixedFractionalSizing
from backtest.strategy import ZScoreStrategy

# ---------------------------------------------------------------------------
# Sweep configuration
# ---------------------------------------------------------------------------

SPREADS = ["wti_calendar", "brent_calendar", "brent_wti"]

# Top signal candidates from Phase 3 research (entry, exit, lookback, use_filters)
SIGNAL_CONFIGS = [
    {"entry_threshold": 1.5, "exit_threshold": 0.5, "lookback": 30, "use_filters": True},
    {"entry_threshold": 1.0, "exit_threshold": 0.3, "lookback": 20, "use_filters": True},
    {"entry_threshold": 2.0, "exit_threshold": 0.75, "lookback": 60, "use_filters": True},
]

# Standard cost model: $2 commission, 5 bps spread, 2 bps slippage
COST_MODEL = CostModel(commission_per_contract=2.0, spread_bps=5.0, slippage_bps=2.0)

SIZING_MODELS = [
    FixedFractionalSizing(risk_pct=0.01, max_leverage=5.0, min_atr=0.10),
    ATRSizing(risk_pct=0.01, max_leverage=5.0, min_atr=0.10),
]

INITIAL_CAPITAL = 100_000.0


# ---------------------------------------------------------------------------
# Run sweep
# ---------------------------------------------------------------------------

def run_sweep(write_to_db: bool = True) -> pd.DataFrame:
    """Run all (spread x signal config x sizing) combinations and return results DataFrame."""
    results = []
    combos = list(product(SPREADS, SIGNAL_CONFIGS, SIZING_MODELS))
    total = len(combos)

    print(f"\nPhase 5 sweep: {total} configurations across {len(SPREADS)} spreads x "
          f"{len(SIGNAL_CONFIGS)} signal configs x {len(SIZING_MODELS)} sizing methods\n")

    for idx, (spread_name, sig_cfg, sizing_model) in enumerate(combos, 1):
        label = f"[{idx}/{total}] {spread_name} | entry={sig_cfg['entry_threshold']} "
        label += f"exit={sig_cfg['exit_threshold']} lb={sig_cfg['lookback']} "
        label += f"sizing={sizing_model.name()}"
        print(label)

        try:
            strategy = ZScoreStrategy(**sig_cfg)
            engine = BacktestEngine(
                strategy=strategy,
                spread_name=spread_name,
                initial_capital=INITIAL_CAPITAL,
                cost_model=COST_MODEL,
                sizing_model=sizing_model,
            )
            res = engine.run(write_to_db=write_to_db)

            row = {
                "spread": spread_name,
                "entry_thr": sig_cfg["entry_threshold"],
                "exit_thr": sig_cfg["exit_threshold"],
                "lookback": sig_cfg["lookback"],
                "filters": sig_cfg["use_filters"],
                "sizing": sizing_model.name(),
                "trades": res["total_trades"],
                "sharpe": res["sharpe"],
                "sortino": res["sortino"],
                "calmar": res["calmar"],
                "max_dd": res["max_drawdown"],
                "win_rate": res["win_rate"],
                "profit_factor": res["profit_factor"],
                "avg_pnl": res["avg_trade_pnl"],
                "avg_dur_days": res["avg_trade_duration_days"],
                "total_pnl": res["realised_pnl"],
                "params_hash": res.get("params_hash", "")[:8],
            }
            results.append(row)
            _print_row(row)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            results.append({
                "spread": spread_name, "sizing": sizing_model.name(),
                "entry_thr": sig_cfg["entry_threshold"],
                "sharpe": float("nan"), "error": str(exc),
            })

    df = pd.DataFrame(results)
    return df


def _print_row(r: dict) -> None:
    sharpe = f"{r['sharpe']:.3f}" if not (r['sharpe'] is None or np.isnan(r['sharpe'])) else "N/A"
    win_rate = f"{r['win_rate']:.0%}" if not (r['win_rate'] is None or np.isnan(r['win_rate'])) else "N/A"
    print(
        f"  → trades={r['trades']:3d}  sharpe={sharpe:>7s}  "
        f"max_dd={r['max_dd']:.2%}  win_rate={win_rate}  "
        f"hash={r['params_hash']}"
    )


def print_summary(df: pd.DataFrame) -> None:
    """Print ranked summary table and best-per-spread stats from sweep results."""
    print("\n" + "=" * 80)
    print("PHASE 5 SWEEP RESULTS - ranked by Sharpe ratio")
    print("=" * 80)

    numeric_cols = ["sharpe", "sortino", "calmar", "max_dd", "win_rate", "profit_factor", "avg_pnl", "avg_dur_days"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    sorted_df = df.sort_values("sharpe", ascending=False)
    display_cols = ["spread", "sizing", "entry_thr", "exit_thr", "lookback",
                    "trades", "sharpe", "sortino", "max_dd", "win_rate", "profit_factor"]
    display_cols = [c for c in display_cols if c in sorted_df.columns]

    pd.set_option("display.float_format", "{:.3f}".format)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.width", 140)
    print(sorted_df[display_cols].to_string(index=False))

    print("\n--- Best run per spread (by Sharpe) ---")
    for spread in SPREADS:
        sub = df[df["spread"] == spread].dropna(subset=["sharpe"])
        if sub.empty:
            print(f"  {spread}: no valid runs")
            continue
        best = sub.loc[sub["sharpe"].idxmax()]
        sharpe_str = f"{best['sharpe']:.3f}" if not np.isnan(best['sharpe']) else "N/A"
        print(
            f"  {spread}: Sharpe={sharpe_str}  sizing={best['sizing']}  "
            f"entry={best['entry_thr']}  lb={best['lookback']}"
        )

    best_overall = df.dropna(subset=["sharpe"])
    if not best_overall.empty:
        best = best_overall.loc[best_overall["sharpe"].idxmax()]
        print(f"\n--- Verification check ---")
        sharpe_val = best['sharpe']
        if not np.isnan(sharpe_val) and sharpe_val > 0.8:
            print(f"  PASS: best Sharpe after costs = {sharpe_val:.3f} > 0.8")
        elif not np.isnan(sharpe_val) and sharpe_val > 0:
            print(f"  MARGINAL: best Sharpe after costs = {sharpe_val:.3f} (target > 0.8)")
        else:
            print(f"  WARN: best Sharpe = {sharpe_val:.3f}; revisit signal or cost assumptions")

        max_dd = best.get("max_dd", float("nan"))
        if not np.isnan(max_dd):
            print(f"  Max drawdown on best run: {max_dd:.2%}")

        max_trade_risk = best.get("avg_pnl", float("nan"))
        print(f"  Avg trade PnL: ${max_trade_risk:.2f}" if not np.isnan(max_trade_risk) else "")

    print()


def run_cost_impact_comparison(write_to_db: bool = True) -> None:
    """Run zero-cost vs. cost-model side-by-side on the best signal config for each spread."""
    print("\n" + "=" * 80)
    print("COST IMPACT COMPARISON - zero-cost vs. with-costs (entry=2.0, exit=0.75, lb=60)")
    print("=" * 80)

    best_sig = SIGNAL_CONFIGS[2]  # entry=2.0, exit=0.75, lb=60 (best candidate)
    sizing = FixedFractionalSizing(risk_pct=0.01, max_leverage=5.0, min_atr=0.10)

    for spread_name in SPREADS:
        # Zero-cost run
        strat_0 = ZScoreStrategy(**best_sig)
        engine_0 = BacktestEngine(
            strategy=strat_0,
            spread_name=spread_name,
            initial_capital=INITIAL_CAPITAL,
            cost_model=None,
            sizing_model=sizing,
        )
        try:
            res_0 = engine_0.run(write_to_db=write_to_db)
        except Exception as e:
            print(f"  {spread_name}: ERROR (zero-cost) - {e}")
            continue

        # With-cost run
        strat_c = ZScoreStrategy(**best_sig)
        engine_c = BacktestEngine(
            strategy=strat_c,
            spread_name=spread_name,
            initial_capital=INITIAL_CAPITAL,
            cost_model=COST_MODEL,
            sizing_model=sizing,
        )
        try:
            res_c = engine_c.run(write_to_db=write_to_db)
        except Exception as e:
            print(f"  {spread_name}: ERROR (with-costs) - {e}")
            continue

        sharpe_0 = res_0["sharpe"]
        sharpe_c = res_c["sharpe"]
        pnl_0 = res_0["realised_pnl"]
        pnl_c = res_c["realised_pnl"]

        fmt = lambda v: f"{v:.3f}" if not (v is None or np.isnan(v)) else "N/A"
        pnl_reduction = (pnl_c - pnl_0) / abs(pnl_0) * 100 if abs(pnl_0) > 1e-8 else 0.0

        print(f"\n  {spread_name}:")
        print(f"    Zero-cost : Sharpe={fmt(sharpe_0)}  PnL=${pnl_0:>12,.0f}")
        print(f"    With-costs: Sharpe={fmt(sharpe_c)}  PnL=${pnl_c:>12,.0f}")
        print(f"    PnL reduction: {pnl_reduction:+.1f}%  ← CostModel impact")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 5 full backtest sweep")
    parser.add_argument("--no-db", action="store_true", help="Skip writing results to DB")
    args = parser.parse_args()

    df = run_sweep(write_to_db=not args.no_db)
    print_summary(df)
    run_cost_impact_comparison(write_to_db=not args.no_db)
