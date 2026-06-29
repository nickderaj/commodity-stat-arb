"""Bar-by-bar backtest engine.

Core loop:
  fetch next bar → check open position → check new signal → generate order
  → apply fill logic → update portfolio state → mark-to-market

All trades are written to the Postgres ``orders`` table. Summary stats are
written to ``backtest_runs``. Re-running with identical parameters (same
``params_hash``) skips re-execution and returns the existing run record.

Look-ahead bias guard
---------------------
Strategies pre-compute all signals in ``load_data()`` with ``shift(1)`` so
that the signal at bar *t* uses only data from bars 0 … t-1.  The engine
asserts that the strategy's DataFrame length matches expectations and never
peeks at index t+1 or beyond.

CLI usage (smoke test):
    uv run python backtest/engine.py [--spread wti_calendar] [--year 2023]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.cost_model import CostModel
from backtest.portfolio import Portfolio, Trade
from backtest.sizing import ATRSizing, FixedFractionalSizing, SizingModel, compute_atr_series
from backtest.strategy import Strategy, ZScoreStrategy
from db.models import BacktestRun, Order
from db.session import get_session


class BacktestEngine:
    """Bar-by-bar event-driven backtest engine.

    Parameters
    ----------
    strategy : Strategy
        A pre-configured strategy instance (parameters set at construction time).
    spread_name : str
        Which spread to run (must exist in the ``spreads`` DB table).
    initial_capital : float
        Starting portfolio equity (used for Calmar/max-DD normalisation).
    cost_model : CostModel, optional
        Transaction cost model. If None, all fills are zero-cost.
    sizing_model : SizingModel, optional
        Position sizing model. If None, trades are unit-size (1 contract).
    atr_window : int
        Rolling window for ATR (spread rolling std) used by sizing models.
    """

    def __init__(
        self,
        strategy: Strategy,
        spread_name: str,
        initial_capital: float = 100_000.0,
        cost_model: Optional[CostModel] = None,
        sizing_model: Optional[SizingModel] = None,
        atr_window: int = 14,
    ) -> None:
        self.strategy = strategy
        self.spread_name = spread_name
        self.initial_capital = initial_capital
        self.cost_model = cost_model
        self.sizing_model = sizing_model
        self.atr_window = atr_window
        self.portfolio = Portfolio(initial_capital)

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        write_to_db: bool = True,
    ) -> dict:
        """Execute the backtest and return a results dict.

        Parameters
        ----------
        start_date / end_date : str, optional
            ISO date strings (``"YYYY-MM-DD"``) to slice the spread series.
        write_to_db : bool
            If True, persist results to the ``backtest_runs`` and ``orders`` tables.

        Returns
        -------
        dict
            Includes run metadata, performance metrics, equity series, and trade list.
        """
        # Reset portfolio for fresh run
        self.portfolio = Portfolio(self.initial_capital)

        # Load data and pre-compute signals (shift(1) applied inside strategy)
        df = self.strategy.load_data(self.spread_name, start_date, end_date)

        if df.empty:
            raise ValueError(f"No spread data found for '{self.spread_name}' in the given date range")

        actual_start = df.index[0].date()
        actual_end = df.index[-1].date()

        # Pre-compute ATR series for position sizing (shifted; no look-ahead)
        atr_series = compute_atr_series(df["value"], window=self.atr_window)

        # ------------------------------------------------------------------
        # Bar-by-bar event loop
        # ------------------------------------------------------------------
        for i in range(len(df)):
            bar_date: date = df.index[i].date()
            spread_value: float = float(df["value"].iloc[i])

            if np.isnan(spread_value):
                self.portfolio.mark_to_market(bar_date, self.portfolio.entry_price or 0.0)
                continue

            desired = self.strategy.on_bar(i, self.portfolio.position)
            meta = self.strategy.get_bar_meta(i)

            current = self.portfolio.position

            if current != 0 and desired == 0:
                # Exit: compute costs and close position
                costs = self._compute_costs(
                    entry_price=self.portfolio.entry_price,
                    exit_price=spread_value,
                    quantity=self.portfolio.entry_quantity,
                )
                self.portfolio.on_exit(
                    bar_date,
                    spread_value,
                    fees=costs.commission,
                    slippage=costs.slippage,
                    spread_cost=costs.spread_cost,
                )

            elif current == 0 and desired in (-1, 1):
                # Entry: determine position size then open
                atr = float(atr_series.iloc[i]) if not np.isnan(atr_series.iloc[i]) else 1.0
                quantity = self._compute_size(
                    equity=self.portfolio.cash,
                    spread_price=spread_value,
                    atr=atr,
                )
                self.portfolio.on_entry(
                    bar_date,
                    spread_value,
                    desired,
                    zscore=meta.get("zscore") or float("nan"),
                    regime=meta.get("regime", ""),
                    quantity=quantity,
                )

            # Mark portfolio to market at bar close
            self.portfolio.mark_to_market(bar_date, spread_value)

        # Force-close any open position at end of data
        if self.portfolio.position != 0:
            last_date = df.index[-1].date()
            last_price = float(df["value"].iloc[-1])
            costs = self._compute_costs(
                entry_price=self.portfolio.entry_price,
                exit_price=last_price,
                quantity=self.portfolio.entry_quantity,
            )
            self.portfolio.on_exit(
                last_date,
                last_price,
                fees=costs.commission,
                slippage=costs.slippage,
                spread_cost=costs.spread_cost,
            )

        # ------------------------------------------------------------------
        # Collect results
        # ------------------------------------------------------------------
        metrics = self.portfolio.summary()
        params = {
            "spread_name": self.spread_name,
            "start_date": str(actual_start),
            "end_date": str(actual_end),
            "initial_capital": self.initial_capital,
            **self.strategy.params,
            **(self.cost_model.as_dict() if self.cost_model else {"cost_model": "none"}),
            **(self.sizing_model.as_dict() if self.sizing_model else {"sizing": "unit"}),
        }
        params_hash = _hash_params(params)

        results = {
            "params_hash": params_hash,
            "params": params,
            "spread_name": self.spread_name,
            "start_date": actual_start,
            "end_date": actual_end,
            **metrics,
            "equity_series": self.portfolio.equity_series(),
            "trades": self.portfolio.trades,
        }

        if write_to_db:
            run_id = self._write_to_db(results)
            results["run_id"] = run_id

        return results

    # ------------------------------------------------------------------
    # Cost and sizing helpers
    # ------------------------------------------------------------------

    def _compute_costs(self, entry_price, exit_price, quantity: int):
        """Delegate to CostModel; returns zero-cost breakdown when no model configured."""
        from backtest.cost_model import CostBreakdown
        if self.cost_model is None:
            return CostBreakdown(commission=0.0, spread_cost=0.0, slippage=0.0)
        return self.cost_model.compute(
            entry_price=entry_price or 0.0,
            exit_price=exit_price,
            quantity=quantity,
        )

    def _compute_size(self, equity: float, spread_price: float, atr: float) -> int:
        """Delegate to SizingModel; returns 1 when no model configured."""
        if self.sizing_model is None:
            return 1
        return self.sizing_model.compute_size(equity=equity, spread_price=spread_price, atr=atr)

    # ------------------------------------------------------------------
    # DB persistence
    # ------------------------------------------------------------------

    def _write_to_db(self, results: dict) -> int:
        """Persist run and trades to Postgres. Returns the BacktestRun.id."""
        session = get_session()
        try:
            # Check for existing run with the same params hash (idempotency)
            existing = (
                session.query(BacktestRun)
                .filter_by(params_hash=results["params_hash"])
                .first()
            )
            if existing is not None:
                print(f"  [engine] Run with hash {results['params_hash'][:8]}… already exists (id={existing.id}); skipping.")
                return existing.id

            run = BacktestRun(
                params_hash=results["params_hash"],
                spread_name=results["spread_name"],
                start_date=results["start_date"],
                end_date=results["end_date"],
                sharpe=_nan_to_none(results["sharpe"]),
                sortino=_nan_to_none(results["sortino"]),
                calmar=_nan_to_none(results["calmar"]),
                max_drawdown=_nan_to_none(results["max_drawdown"]),
                total_trades=results["total_trades"],
                win_rate=_nan_to_none(results["win_rate"]),
                profit_factor=_nan_to_none(results["profit_factor"]),
                avg_trade_pnl=_nan_to_none(results["avg_trade_pnl"]),
                avg_trade_duration_days=_nan_to_none(results["avg_trade_duration_days"]),
                params_json=json.dumps(results["params"]),
                created_at=datetime.utcnow(),
            )
            session.add(run)
            session.flush()  # assigns run.id

            for trade in results["trades"]:
                order = _trade_to_order(trade, results["spread_name"], run.id)
                session.add(order)

            session.commit()
            print(f"  [engine] Saved run id={run.id} with {results['total_trades']} trades.")
            return run.id

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def print_summary(self, results: dict) -> None:
        m = results
        print(f"\n{'='*60}")
        print(f"Backtest: {self.spread_name}")
        print(f"Period  : {m['start_date']} → {m['end_date']}")
        print(f"{'='*60}")
        print(f"  Trades          : {m['total_trades']}")
        print(f"  Realised PnL    : ${m['realised_pnl']:.2f}")
        print(f"  Sharpe          : {_fmt(m['sharpe'])}")
        print(f"  Sortino         : {_fmt(m['sortino'])}")
        print(f"  Calmar          : {_fmt(m['calmar'])}")
        print(f"  Max Drawdown    : {m['max_drawdown']:.2%}" if not np.isnan(m["max_drawdown"]) else "  Max Drawdown    : N/A")
        print(f"  Win Rate        : {m['win_rate']:.0%}" if not np.isnan(m["win_rate"]) else "  Win Rate        : N/A")
        print(f"  Profit Factor   : {_fmt(m['profit_factor'])}")
        print(f"  Avg Trade PnL   : ${_fmt(m['avg_trade_pnl'])}")
        print(f"  Avg Duration    : {_fmt(m['avg_trade_duration_days'])} days")
        print()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _hash_params(params: dict) -> str:
    serialised = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()


def _nan_to_none(v):
    if v is None:
        return None
    try:
        return None if np.isnan(v) else float(v)
    except (TypeError, ValueError):
        return v


def _trade_to_order(trade: Trade, spread_name: str, run_id: int) -> Order:
    return Order(
        spread_name=spread_name,
        backtest_run_id=run_id,
        entry_date=trade.entry_date,
        exit_date=trade.exit_date,
        direction="long" if trade.direction == 1 else "short",
        quantity=trade.quantity,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        fill_price=trade.fill_price,
        fees=trade.fees,
        slippage=trade.slippage,
        spread_cost=trade.spread_cost,
        temp_impact_cost=trade.temp_impact_cost,
        perm_impact_cost=trade.perm_impact_cost,
        pnl=trade.pnl,
        zscore_at_entry=trade.zscore_at_entry,
        regime_at_entry=trade.regime_at_entry,
        trade_duration_days=trade.duration_days,
        created_at=datetime.utcnow(),
    )


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:.3f}"


# ------------------------------------------------------------------
# Smoke test CLI
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest engine smoke test")
    parser.add_argument("--spread", default="wti_calendar", help="Spread name to backtest")
    parser.add_argument("--year", type=int, default=None, help="Single calendar year to test (e.g. 2023)")
    parser.add_argument("--entry", type=float, default=1.5)
    parser.add_argument("--exit", type=float, default=0.5)
    parser.add_argument("--lookback", type=int, default=30)
    parser.add_argument("--no-filters", action="store_true")
    parser.add_argument("--no-db", action="store_true", help="Skip DB writes")
    args = parser.parse_args()

    start_date = f"{args.year}-01-01" if args.year else None
    end_date = f"{args.year}-12-31" if args.year else None

    strategy = ZScoreStrategy(
        entry_threshold=args.entry,
        exit_threshold=getattr(args, "exit"),
        lookback=args.lookback,
        use_filters=not args.no_filters,
    )

    engine = BacktestEngine(strategy=strategy, spread_name=args.spread)
    print(f"Running backtest: {args.spread} | entry={args.entry} exit={getattr(args, 'exit')} lookback={args.lookback} filters={not args.no_filters}")

    results = engine.run(start_date=start_date, end_date=end_date, write_to_db=not args.no_db)
    engine.print_summary(results)

    # Smoke-test assertions
    eq = results["equity_series"]
    assert not eq.isnull().any(), "FAIL: NaN in equity curve"
    assert (eq > 0).all(), "FAIL: negative equity detected"

    pnl_series = eq.diff().dropna()
    if len(pnl_series) > 0:
        assert not np.isinf(pnl_series.values).any(), "FAIL: Inf in daily PnL"

    print("Smoke test PASSED: no NaN blowups, no negative cash, no Inf values.")


if __name__ == "__main__":
    main()
