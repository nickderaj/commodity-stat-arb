"""Automated data pipeline: ingest raw contracts then build all spread series.

Runs the two data steps in sequence so a fresh setup only needs one command:

    uv run python scripts/ingest_and_build.py

Optionally scope to a single spread and/or date range:

    uv run python scripts/ingest_and_build.py --spread brent_wti
    uv run python scripts/ingest_and_build.py --start 2020-01-01 --end 2024-12-31
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.ingest import main as ingest_main
from data.build_spreads import main as build_main


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest raw OHLCV bars then build continuous spread series"
    )
    parser.add_argument("--start", default="2018-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=str(date.today()), help="End date YYYY-MM-DD")
    parser.add_argument("--spread", default=None, help="Limit to this spread name only")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    print("=" * 60)
    print("STEP 1/2: Ingesting raw contract OHLCV bars")
    print("=" * 60)
    # Patch sys.argv so each sub-main sees the right flags
    sys.argv = ["ingest"]
    if args.spread:
        sys.argv += ["--spread", args.spread]
    sys.argv += ["--start", args.start, "--end", args.end]
    ingest_main()

    print()
    print("=" * 60)
    print("STEP 2/2: Building continuous spread series")
    print("=" * 60)
    sys.argv = ["build_spreads"]
    if args.spread:
        sys.argv += ["--spread", args.spread]
    sys.argv += ["--start", args.start, "--end", args.end]
    build_main()

    print()
    print("Done. Data is ready in the database.")
    print("Next: uv run python scripts/run_all_backtests.py")


if __name__ == "__main__":
    main()
