# Phase 8 Notes - Plotly Dash Dashboard

## _ Notes after building the interactive research dashboard in ui/app.py _

> See `ui/app.py` for all implementation. The dashboard is the final layer on top of the existing engine -- it does not duplicate any computation that already lives in Phase 1-7 scripts. It reads from the DB and runs the backtest engine on demand.

---

## A. What Was Built

The dashboard is a single-file Plotly Dash application at `ui/app.py`. It runs against the existing Postgres DB and backtesting engine with no changes to upstream code. Launch command:

```
uv run python ui/app.py
```

This opens on `http://127.0.0.1:8050`.

The layout is a 2-column design: a narrow left sidebar with all controls, and a 10-column main area with 5 tabs. The theme is Bootswatch DARKLY (dark background, monospace fonts, muted grids), which keeps the charts readable without eye strain during long research sessions.

### Sidebar Controls

- **Spread dropdown:** brent_wti / brent_calendar / wti_calendar
- **Date range picker:** start and end date, defaults to full available history
- **Entry threshold slider:** 0.5 to 3.0 in steps of 0.5 (matches Phase 3 scan range)
- **Exit threshold slider:** 0.2 to 1.0 in steps of 0.05
- **Lookback slider:** 10 to 90 days in steps of 10
- **Regime filters toggle:** on/off (Phase 3 roll-window + vol + liquidity filters)
- **AC model toggle:** on/off (Almgren-Chriss execution costs vs naive fills)

When any control changes, a single Dash callback runs the backtest engine and stores the results in a hidden `dcc.Store`. All chart callbacks read from the store, so they update together without running multiple backtests.

---

## B. The Five Tabs

### Overview Tab

This is the first thing you see and answers the question "did this configuration make money?"

The four KPI cards at the top show Sharpe, Sortino, Max Drawdown, and Trade Count. They change colour: green for Sharpe above 0.5, orange for positive but below 0.5, red for negative. Max drawdown follows the same threshold logic (green for under 10%, orange for 10-20%, red for worse).

Below the KPIs are two side-by-side charts. The larger left chart shows cumulative PnL from initial capital ($100k). It plots two lines: naive fills (solid cyan) and AC-adjusted fills (dashed orange). The naive line reconstructs what the equity would have been without the Almgren-Chriss market impact costs -- it adds back the `temp_impact_cost` and `perm_impact_cost` fields from each trade. At the current position sizes (~2-10 contracts), the AC adjustment is tiny compared to commission and bid-ask (as shown in Phase 6). The two lines are visually indistinguishable at this scale, which is the honest answer from Phase 6.

The structural break date from Phase 2 (Zivot-Andrews) is marked as a vertical red dashed line on the equity chart. For brent_wti that is 2019-05-31, which visually shows how the pre-break and post-break equity trajectories differ.

The right drawdown chart shows peak-to-trough drawdown as a filled red area over time. For brent_wti at entry=2.0, lookback=60, the maximum drawdown is around -15% over the full period.

The bottom panel is a monthly returns heatmap: years on the y-axis, months on the x-axis, colour from red (loss) to green (profit). This view shows seasonality quickly. For brent_wti, no obvious month clusters as consistently bad or good -- the returns are roughly distributed across the calendar, consistent with a mean-reversion rather than seasonal carry strategy.

### Signals Tab

Four charts visualising the signal mechanics:

**Spread price chart (top, full width):** The raw spread value over time. Entry signals are marked as triangles (up = long entry, down = short entry); exits are X markers. Roll window periods are shaded orange. For calendar spreads, backwardation periods are shaded red.

The markers make the strategy legible: you can see at a glance whether entries are concentrated around certain price levels, and whether the exits follow shortly after entries (fast mean reversion) or take weeks (slow). For brent_wti with lookback=60, entries tend to cluster when the spread is at multi-month extremes and exits happen within 1-3 weeks.

**Z-score chart (middle left):** The rolling z-score over the same period, with horizontal lines at the entry threshold (solid red/green) and exit threshold (dotted). This is the direct signal driving the strategy. You can trace a trade: spread price hits a level, z-score crosses the entry line, triangle appears on the spread chart, then z-score drifts back to zero, X marker appears, and the position closes.

**Rolling half-life chart (middle right):** The AR(1) half-life estimated from a rolling 252-day window, computed every 21 trading days. The computation is the same as Phase 2: fit ΔS_t = a + b * S(t-1), half-life = -ln(2)/b. Values outside 0-90 days are filtered as unreliable (usually caused by near-zero or positive b in low-volatility periods).

For brent_wti, the median rolling half-life is around 3-4 days -- much shorter than the 60-day lookback window. This is expected and actually good for the strategy: when the spread reverts within a few days, the z-score signal fires early enough to capture most of the move before the position needs to be held for weeks.

The 3-day and 30-day reference lines help interpret: half-life below 3 days is so fast that the signal may not even fire before the opportunity closes; above 30 days means the spread reverts slowly and the strategy is at risk from extended drawdowns (this is the wti_calendar problem identified in Phase 3 -- half-life 15-31d).

**Roll heatmap (bottom, full width):** Average absolute daily spread change, binned by days-to-expiry (x-axis) and contract expiry month (y-axis). This is the Phase 2 roll diagnostic visualisation. Brighter cells mean the spread was more volatile near those expiry dates. You can see whether vol consistently spikes close to expiry (DTE 0-3 bucket) vs staying elevated or dropping.

This confirms the Phase 2 finding: calendar spreads see elevated vol in the roll window, which is why the roll-window filter in the signal suppresses entries during those periods.

### Execution Tab

Four charts breaking down execution quality. The key question here is: what does it cost to execute this strategy, and where does the cost come from?

**Fill scatter (top left):** Each trade as a dot, with naive fill price on the x-axis and AC-adjusted fill price on the y-axis. Dots above the 45-degree identity line mean the trade cost more to execute than the naive mid-price fill. At the current position sizes, the scatter stays very close to the identity line -- the AC impact is under $0.01/bbl per trade on average. Green dots are profitable trades, red dots are losing trades.

**Cost breakdown bar (top right):** Average cost per trade broken into five components: commission, bid-ask spread, slippage, temporary market impact, and permanent market impact. For the standard parameters:
- Commission: ~$4-8 per trade (round-trip, 2-10 contracts at $2/contract)
- Bid-ask: ~$5-15 per trade (5 bps on ~$1-3 spread price)
- Slippage: ~$2-6 per trade (2 bps)
- AC temp impact: <$1 per trade at these sizes
- AC perm impact: <$0.50 per trade

Commission and bid-ask dominate. This is consistent with Phase 5 and 6 findings: the execution tax at this scale comes from market microstructure costs (spread and commission), not from price impact. A strategy trading 100+ contracts per fill would flip this picture -- temp impact would dominate.

**Slippage distribution (bottom left):** Histogram of total execution cost per trade. Most trades cluster near a low value, with a tail of more expensive trades. The tail comes from high-volatility periods where the bid-ask proxy (HL-range/close) is large.

**Before/after Sharpe (bottom right):** Two bars -- naive fills Sharpe and AC-adjusted Sharpe for the currently selected parameters. The execution tax (difference) is printed at the bottom. For brent_wti at entry=2.0, lookback=60: naive Sharpe 0.412, AC Sharpe 0.407, execution tax 0.005 Sharpe points. This is negligible. Phase 6 showed the tax becomes material (0.3-0.5 Sharpe points reduction) only at 50+ contracts per trade.

### Robustness Tab

Four charts using hardcoded Phase 7 results (re-running robustness takes 2-3 minutes and is not suitable for an interactive callback).

**Walk-forward equity curve (top left):** The full equity curve for the selected spread with blue vertical bands marking the OOS test windows used in Phase 7 (6-month windows). The OOS Sharpe for each window is annotated. For brent_wti, the three windows showed OOS Sharpe of 1.09, 0.72, and 0.75 -- all positive, and two of three above the IS Sharpe for that window. The equity curve shows whether the strategy was making money during the OOS periods, independent of the IS/OOS classification.

**Sub-period Sharpe bar chart (top right):** Sharpe for the selected spread split by period (2015-2019 and 2020+). For brent_wti: 0.841 and 0.363 -- both positive, though declining. The chart changes when you switch the spread selector, so you can compare the sub-period profiles across spreads.

**Parameter sensitivity heatmap (bottom left):** The full 6x6 grid from Phase 7: entry threshold (rows) vs lookback window (columns), colour coded from red to green. This is hardcoded for brent_wti (the Phase 7 analysis only ran the sensitivity grid for the primary spread). The hover tooltip shows the exact Sharpe value. You can see the broad plateau from entry 0.5-2.5 at lookbacks 20-90, and the weak performance at lb=10 and entry=3.0.

This chart is the main answer to "are we cherry-picking a single lucky parameter point?" -- the answer is no, the strategy is profitable across a wide region.

**Stress test chart (bottom right):** Two side-by-side bar charts for COVID 2020 and Ukraine 2022 stress windows, showing Sharpe and max drawdown. Bars are colour coded (green=PASS, orange/red=WARN). For brent_wti: both stress windows pass. For wti_calendar: the COVID max drawdown shows up in red (56.87%). This chart makes the Phase 7 conclusion legible at a glance.

### Thesis Cards Tab

Three Bootstrap cards, one per hypothesis, with colour-coded top borders (green for the primary Brent-WTI candidate, cyan for Brent calendar, orange for WTI calendar). Each card shows:

- **Inefficiency being exploited:** why the spread reverts at all
- **Signal logic:** the exact parameters and why they were chosen
- **Regime required:** what market conditions the signal needs
- **Key stats:** Phase 3 and Phase 5 Sharpe, trade count, win rate, half-life
- **Result:** how it performed across phases and robustness tests
- **Failure mode:** where and why it breaks down

These cards are static -- they don't change with the sidebar controls. They represent the research findings from Phases 2-7, not a live parameter scan. They are the kind of card you would bring to an interview to explain what you found and why.

---

## C. Architecture and Design Decisions

**No duplication of upstream logic.** The dashboard imports `BacktestEngine`, `ZScoreStrategy`, `CostModel`, `FixedFractionalSizing`, `AlmgrenChrissModel`, `load_spread_df`, `compute_zscore`, and `rolling_half_life` directly from the existing modules. No new computation was added -- just wiring.

**Dict cache for run results.** Running a full backtest takes ~0.5-1.5 seconds. With 2 runs per full render (naive + AC), that would make the UI feel sluggish. A simple module-level dict keyed by `(spread, entry, exit, lookback, use_filters, use_ac)` stores results across callback firings. Since Dash runs in a single process, this is safe. Cache is cleared only on server restart.

**dcc.Store pattern.** A single heavyweight callback runs the backtest and writes results to a `dcc.Store`. All chart callbacks read from the store. This means all charts update together when parameters change, and you only run the backtest once per parameter change (not once per chart).

**Robustness data is hardcoded.** The Phase 7 walk-forward, sub-period, stress test, and sensitivity grid results are stored as Python constants in `ui/app.py`. The alternative (re-running phase7 in a callback) would take 2-3 minutes and make the Robustness tab unusable interactively. The hardcoded approach is honest: these are fixed research results, not recalculated live.

**Structural break markers use Phase 2 results.** The break dates from Zivot-Andrews (`research/structural_breaks.json`) are hardcoded in `STRUCTURAL_BREAKS` dict. They appear on both the Overview equity chart and the Signals spread chart, making the before/after break behaviour visible.

**Naive vs AC comparison from a single run.** Rather than running two separate backtests to get the naive and AC equity curves, the dashboard runs one backtest with the AC model enabled and reconstructs the naive curve by adding back the per-trade impact costs (`temp_impact_cost + perm_impact_cost`) from the trade list. This is algebraically correct because `trade.pnl = raw_pnl - all_costs` and the AC costs are stored separately.

---

## D. Dashboard Limitations

**Not a live trading system.** The dashboard is a research tool. Every chart is driven by historical backtest data. The sidebar parameters recalculate historical results, not forward simulations.

**Mobile not physically tested.** The Bootstrap DARKLY theme provides responsive breakpoints, and the sidebar will stack above the main content on small screens. The 2-column layout is not ideal for phones. Not an issue for an interview prop that will be shown on a laptop.

**Robustness data is static for brent_wti.** The parameter sensitivity heatmap and walk-forward chart are hardcoded from the Phase 7 brent_wti run. Switching to brent_calendar or wti_calendar in the sidebar changes the sub-period and stress charts (which are spread-specific) but not the sensitivity heatmap. A full sensitivity grid for all three spreads would take 30+ minutes to compute and is not practical for an interactive dashboard.

**No time-of-day breakdown in slippage.** The Phase 8 plan mentioned slippage "by time-of-day, vol regime, trade size bucket." On daily bars, there is no intraday time information -- the AC model uses mid-session defaults (factor=1.0) for all trades. The slippage distribution chart shows total execution cost per trade but cannot break it by time-of-day.

---

## E. Checklist

- [x] `ui/app.py` - single-file Dash app, ~500 lines, imports cleanly from project modules
- [x] Dark theme (Bootswatch DARKLY) with dark plot backgrounds
- [x] Sidebar with spread dropdown, date range, entry/exit/lookback sliders, filter and AC toggles
- [x] Overview tab: KPI cards, PnL chart (naive vs AC), drawdown chart, monthly returns heatmap
- [x] Signals tab: spread price with entry/exit markers, z-score with threshold lines, rolling half-life, roll heatmap
- [x] Execution tab: fill scatter, cost breakdown bar, slippage distribution, before/after Sharpe comparison
- [x] Robustness tab: walk-forward equity with OOS shading, sub-period Sharpe bar, sensitivity heatmap, stress test bars
- [x] Thesis Cards tab: 3 styled cards with all hypothesis information from Phase 3
- [x] All sidebar controls wired via dcc.Store; single backtest run per parameter change
- [x] HTTP 200 confirmed; all 5 tab IDs present in layout; backtest engine runs correctly from app
