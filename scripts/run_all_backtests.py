"""Run all backtest phases in sequence: sweep, AC comparison, robustness checks.

Equivalent to running the three phase scripts one after another:

    uv run python scripts/run_phase5_sweep.py
    uv run python scripts/run_phase6_ac.py
    uv run python scripts/run_phase7_robustness.py

Use this for a clean full run after ingesting fresh data:

    uv run python scripts/run_all_backtests.py

Pass --no-db to skip writing results back to the database (dry run):

    uv run python scripts/run_all_backtests.py --no-db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.run_phase5_sweep import run_sweep, print_summary as sweep_summary
from scripts.run_phase6_ac import run_naive_vs_ac, run_eta_sensitivity, print_tod_curve, print_summary as ac_summary
from scripts.run_phase7_robustness import run_sub_period, run_walk_forward, run_parameter_sensitivity, run_stress_tests


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all backtest phases in sequence")
    parser.add_argument("--no-db", action="store_true", help="Skip writing results to DB")
    args = parser.parse_args()

    write = not args.no_db

    print("\n" + "=" * 60)
    print("PHASE 5: Full parameter sweep with costs")
    print("=" * 60)
    sweep_df = run_sweep(write_to_db=write)
    sweep_summary(sweep_df)

    print("\n" + "=" * 60)
    print("PHASE 6: Almgren-Chriss execution cost comparison")
    print("=" * 60)
    print_tod_curve()
    ac_df = run_naive_vs_ac(write_to_db=write)
    run_eta_sensitivity(write_to_db=write)
    ac_summary(ac_df)

    print("\n" + "=" * 60)
    print("PHASE 7: Robustness checks")
    print("=" * 60)
    run_sub_period(write_to_db=write)
    run_walk_forward(write_to_db=write)
    run_parameter_sensitivity(write_to_db=write)
    run_stress_tests(write_to_db=write)

    print("\n" + "=" * 60)
    print("All backtest phases complete.")
    print("Launch the dashboard: uv run python ui/app.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
