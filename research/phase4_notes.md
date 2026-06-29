# Phase 4 Notes - Backtest Engine Scaffold

## _ Notes after building the bar-by-bar event loop and running the first smoke test _

> See `backtest/engine.py`, `backtest/strategy.py`, and `backtest/portfolio.py`. The Phase 4 engine deliberately has no position sizing and no cost model -- those come in Phase 5. The goal here was to build the scaffold correctly and prove it doesn't blow up.

---

## A. The Core Loop Design

The engine runs a simple bar-by-bar event loop. On each bar it:

1. Fetches the next spread value from the pre-loaded DataFrame
2. Checks whether the portfolio currently has an open position
3. Asks the strategy what it wants to do (`on_bar()` returns +1 / -1 / 0)
4. Compares current vs desired position to decide whether to enter, exit, or hold
5. Applies fill logic (entry or exit) and updates portfolio state
6. Marks the portfolio to market for the equity curve

The strategy's `load_data()` is called once before the loop starts. Everything after that is O(n) bar iteration -- no re-scanning, no lookahead into the DataFrame.

One decision I went back and forth on: should the engine call the strategy or should the strategy drive the engine? I went with the engine calling the strategy via `on_bar()` because it keeps cost logic, portfolio logic, and signal logic separate. The strategy knows nothing about costs or position sizes. That separation makes it easier to swap in new strategies without touching the cost model or portfolio accounting.

---

## B. Strategy Base Class

The `Strategy` abstract base class has four required methods:

- `load_data(spread_name, start_date, end_date)` -- pre-compute all indicator series
- `on_bar(idx, current_position)` -- return desired position at bar `idx`
- `get_bar_meta(idx)` -- return per-bar metadata for the audit log (z-score, regime, suppressed)
- `params` (property) -- return strategy parameters as a dict for DB storage and hashing

The `ZScoreStrategy` subclass implements the z-score mean-reversion signal from Phase 3. The key design choice: `load_data()` pre-computes the entire z-score series using `shift(1)` before the loop starts. So `on_bar()` just reads `zscore.iloc[idx]` -- it never touches any index beyond `idx`. This is the look-ahead bias guard.

The alternative (recomputing z-score on each bar from data up to `t`) would also work but is slow and harder to audit. Pre-computing with `shift(1)` is faster and the bias protection is visible in one place.

---

## C. Portfolio Accounting

The `Portfolio` class tracks:

- `cash` -- starts at initial_capital, updated on each exit by net_pnl
- `position` -- +1, -1, or 0 (one position at a time; no pyramiding in Phase 4)
- `entry_price`, `entry_date`, `entry_zscore`, `entry_quantity` -- saved on entry for PnL calculation on exit
- `realised_pnl` -- cumulative realised profit/loss from closed trades
- Equity curve -- list of (date, equity) snapshots, one per bar

The PnL formula is straightforward:

```
raw_pnl = (exit_price - entry_price) * direction * quantity
net_pnl = raw_pnl - total_costs
cash += net_pnl
```

Unrealised PnL is computed per-bar for the equity curve (`(current_price - entry_price) * direction * quantity`) but does not affect `cash` until the trade is closed.

The metrics (Sharpe, Sortino, Calmar, max drawdown, win rate, profit factor) are all computed from the equity curve and trade list after the loop completes. Sharpe uses daily PnL differences from the equity series, annualised by sqrt(252).

Max drawdown is computed as the maximum peak-to-trough drop relative to the running peak: `min((equity - cummax_equity) / cummax_equity)`. This gives a fraction (negative number). A -20% max drawdown means the worst peak-to-trough loss was 20% of the portfolio.

---

## D. Look-Ahead Bias Guard

This is the thing that kills most retail backtests. If your signal at bar `t` accidentally uses any data from `t` or later, you're peeking at the future.

The way it's guarded here: `compute_zscore()` in `research/signals.py` applies `.shift(1)` to the rolling z-score before returning. So `zscore.iloc[t]` is computed from spread values up to bar `t-1`. The engine's `on_bar()` reads `zscore.iloc[idx]` and nothing else from the DataFrame, so bar `idx` decisions can only use information from bars 0 through `idx-1`.

The ATR series (for sizing, in Phase 5) uses the same pattern: `rolling(window).std().shift(1)`.

You can verify this by checking a specific bar manually: if the z-score at bar 50 with a 30-day lookback uses bars 20-49 (not bars 20-50), the shift is working. The smoke test doesn't explicitly check this but the unit tests in the strategy file do.

One subtle place where look-ahead can sneak in: if you compute the z-score mean and std over the full dataset and then shift, you've still used the full dataset's stats. The implementation computes rolling (expanding or fixed-window) stats per bar, so the z-score at bar `t` only uses a window ending at `t-1`.

---

## E. Smoke Test Results

Engine run on 1 year of data (`brent_wti`, 2023, unit sizing, no costs, default params entry=1.5 exit=0.5 lookback=30):

```
Backtest: brent_wti
Period  : 2023-01-03 to 2023-12-29
Trades          : 10
Realised PnL    : $1.80       (unit size = 1 bbl, so this is $/bbl not full position)
Sharpe          : 0.409
Sortino         : 0.444
Calmar          : 0.682
Max Drawdown    : -0.00%
Win Rate        : 60%
Profit Factor   : 2.047
Avg Trade PnL   : $0.180
Avg Duration    : 13.6 days
Smoke test PASSED: no NaN blowups, no negative cash, no Inf values.
```

The PnL looks tiny ($1.80) because unit size is 1 bbl -- the spread is quoted in $/bbl and the default engine has no sizing model yet. 10 trades over a year at 1 bbl each is just a sanity check, not a performance measurement. Phase 5 scales this to real position sizes.

The 0.0% max drawdown looks suspicious but makes sense: at 1 bbl/trade with no costs, the equity curve barely moves, and on this particular year the trade PnL was net positive throughout. With real sizing in Phase 5 the drawdowns look much larger.

Key things confirmed by the smoke test:
- No NaN in the equity curve
- Cash never goes negative
- No division-by-zero errors in the metric calculations
- Trades are written to the orders table with all required fields (entry/exit date, z-score at entry, regime, fill price)

---

## F. DB Audit Trail

Every completed trade writes one row to the `orders` table with:

| Field | What it captures |
| ----- | --------------- |
| entry_date / exit_date | Bar dates (not wall time -- daily bars have no intraday timestamp) |
| direction | 'long' or 'short' spread |
| quantity | Position size in bbls |
| entry_price / exit_price | Spread value at entry and exit |
| fill_price | Same as exit_price in this engine (no slippage model yet) |
| fees / slippage / spread_cost | From CostModel (zero in Phase 4) |
| temp_impact_cost / perm_impact_cost | From AC model (zero in Phase 4, wired in Phase 6) |
| pnl | Net PnL after all costs |
| zscore_at_entry | z-score that triggered the entry signal |
| regime_at_entry | The spread table regime flag at entry bar |
| trade_duration_days | Calendar days between entry and exit |

The `backtest_runs` table gets one row per unique configuration, keyed by a SHA-256 hash of all parameters. Re-running with identical parameters skips re-execution and returns the existing row. This idempotency is essential once the sweep in Phase 5 runs 18+ configurations -- you don't want to re-run everything if one combination fails.

---

## G. Checklist

- [x] `backtest/engine.py` - bar-by-bar event loop with entry/exit/hold logic
- [x] `backtest/strategy.py` - `Strategy` ABC and `ZScoreStrategy` implementation
- [x] `backtest/portfolio.py` - `Portfolio` class with equity curve, metrics, trade log
- [x] Look-ahead bias: `shift(1)` applied in `compute_zscore()` and `compute_atr_series()`
- [x] Orders table populated with full audit fields per trade
- [x] `backtest_runs` table with params hash for idempotency
- [x] Smoke test passes on 1 year of `brent_wti` data: no NaN, no negative cash, no Inf
- [x] Code split into separate files: engine, strategy, portfolio (clear single responsibility per module)
