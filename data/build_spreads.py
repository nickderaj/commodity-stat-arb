"""Build and store all spread series.

Usage:
    python -m data.build_spreads
    python -m data.build_spreads --start 2018-01-01
"""

from __future__ import annotations

import argparse
from datetime import date

from config.loader import load_all_spreads
from data.series_builder import SeriesBuilder

_DEFAULT_START = date(2018, 1, 1)
_DEFAULT_END = date.today()


def main() -> None:
    """Build and persist all configured spread series from raw contract bars."""
    parser = argparse.ArgumentParser(description="Build continuous spread series from ingested data")
    parser.add_argument("--start", default=str(_DEFAULT_START))
    parser.add_argument("--end", default=str(_DEFAULT_END))
    parser.add_argument("--spread", default=None, help="Build only this spread name")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    spreads = load_all_spreads()
    if args.spread:
        spreads = [s for s in spreads if s.name == args.spread]

    for spread in spreads:
        print(f"\nBuilding spread: {spread.display_name}")
        builder = SeriesBuilder(spread, start, end)
        builder.save_to_db()

    print("\nSpread build complete.")


if __name__ == "__main__":
    main()
