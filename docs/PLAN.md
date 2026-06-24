# Project 1 — Commodities Microstructure Stat-Arb Engine

## Phased Build Plan

> **Goal:** Build a **pair-agnostic** commodity futures stat-arb research and execution platform — proven first on Brent/WTI and crude calendar spreads, then extended to any cointegrated pair via a screening pipeline — with (stylized) microstructure diagnostics, an Almgren-Chriss execution simulation, and an interview-ready Plotly Dash dashboard.
>
> **Design principle:** Every module operates on a generic `SpreadDefinition` config object, never a hardcoded ticker. Adding a commodity is a config entry + a screening pass, not a rewrite. See [`PHASE0_FINANCIAL_REASONING.md`](./PHASE0_FINANCIAL_REASONING.md) for the economic thesis behind every trade and the generalization framework.
>
> **Stack:** Python · Postgres · Docker · Redis · pandas · numpy · statsmodels · scipy · SQLAlchemy · Plotly Dash · Databento / Barchart / Nasdaq Data Link (contract-level monthlies) · yfinance (continuous front-months)

---

## Table of Contents

1. [Phase 1 — Project Skeleton & Data Infrastructure](#phase-1)
2. [Phase 2 — Microstructure Diagnostics & Statistical Tests](#phase-2)
3. [Phase 2.5 — Pair Screening (cointegration universe)](#phase-2-5)
4. [Phase 3 — Signal Design & Regime Filters](#phase-3)
5. [Phase 4 — Backtest Engine Scaffold](#phase-4)
6. [Phase 5 — Full Backtest with Costs](#phase-5)
7. [Phase 6 — Almgren-Chriss Execution Simulator](#phase-6)
8. [Phase 7 — Robustness Testing](#phase-7)
9. [Phase 8 — Plotly Dash Dashboard](#phase-8)
10. [Phase 9 — Research Memo & GitHub Polish](#phase-9)
11. [Phase 10 — Interview Prep & Paper-Trade Scaffold](#phase-10)
12. [CV Bullets — Ready to Use](#cv-bullets)
13. [Master Completion Checklist](#master-checklist)

---

<a name="phase-1"></a>

## Phase 1 — Project Skeleton & Data Infrastructure

**Focus: Data**

### Project skeleton, DB schema, ingestion pipeline

- [ ] Create GitHub repo with clean directory structure:
  - `data/` — ingestion scripts and raw data utilities
  - `research/` — notebooks, hypothesis notes, diagnostics
  - `backtest/` — engine, strategy classes, portfolio
  - `execution/` — Almgren-Chriss model, cost components
  - `config/` — `SpreadDefinition` YAML configs (one per pair); no tickers hardcoded in code
  - `ui/` — Plotly Dash app
- [ ] Write `docker-compose.yml` spinning up Postgres 16 + pgAdmin; define `.env` with DB credentials
- [ ] Define DB schema and write SQLAlchemy models for:
  - `contracts` — metadata (ticker, exchange, expiry, first_notice_date, last_trade_date)
  - `ohlcv_bars` — OHLCV at daily resolution per contract
  - `spreads` — computed spread series with regime flags
  - `roll_calendar` — historical roll dates and OI crossover dates
  - `signals` — signal values, z-scores, entry/exit flags per bar
  - `orders` — full audit log of all simulated trades
  - `backtest_runs` — run metadata, parameters hash, summary stats
- [ ] Implement the `SpreadDefinition` config loader (`config/*.yaml` → typed object): legs, weights/hedge ratio, spread type (`calendar` / `cross_market` / `crack` / `crush` / `ratio`), economic tether, expected half-life. **All downstream code reads tickers from configs — never hardcoded.**
- [ ] **Data sourcing (two tiers):**
  - **Contract-level monthlies** (required for calendar spreads): source individual contract months (CLF, CLG, CLH … BZF, BZG …) from **Databento / Barchart / Nasdaq Data Link**. ⚠️ yfinance does _not_ reliably serve expired individual contract months — do not rely on it for calendars.
  - **Continuous front-months** (sufficient for cross-market spreads like Brent–WTI): yfinance `CL=F`, `BZ=F` as a free, fast path and as a sanity cross-check against the paid feed.
- [ ] Write `data/ingest.py`: pull daily OHLCV for the contract months named by the active `SpreadDefinition`(s) from the configured provider and write to Postgres; provider is a config/adapter, not hardcoded

### Roll calendar, continuous series builder, spread construction

- [ ] Build `data/roll_calendar.py`: expiry/first-notice/last-trade dates per exchange-product (CME WTI, ICE Brent to start) for last 5+ years; store in `roll_calendar` table keyed by product so new products are added as data, not code
- [ ] Build `data/series_builder.py` (pair-agnostic): stitch individual contracts into continuous front-month and second-month series for any product, using both calendar-based roll (N days before expiry) and OI-based roll — expose as a config param
- [ ] Construct and store spread series from `SpreadDefinition` configs (the engine builds whatever spreads are configured). First three configs:
  - WTI calendar spread: `M1 – M2` (`spread_type: calendar`)
  - Brent calendar spread: `M1 – M2` (`spread_type: calendar`)
  - Cross-market spread: `Brent_M1 – WTI_M1` (`spread_type: cross_market`; hedge ratio β from cointegration)
- [ ] Plot all configured spread series in a Jupyter notebook; mark roll dates on the chart; visually inspect for roll artefacts (false jumps at expiry) and fix before proceeding
- [ ] Annotate roll windows (roll_offset_days before expiry, inclusive) as a flag column in the `spreads` table

---

### ✅ Phase 1 Verification

Before proceeding to Phase 2, confirm all of the following:

- [ ] `docker-compose up` runs without errors; Postgres is accessible via pgAdmin
- [ ] All SQLAlchemy models migrate cleanly with no errors
- [ ] `ingest.py` pulls data for at least 5 years of history for WTI and Brent contracts
- [ ] `series_builder.py` produces a continuous front-month and second-month series for both WTI and Brent
- [ ] All three spread series (WTI cal, Brent cal, Brent–WTI) are stored in the `spreads` table
- [ ] Notebook chart of spread series looks sensible: no unexplained discontinuities; roll artefacts identified and handled
- [ ] Roll window flag is populated in the `spreads` table

---

<a name="phase-2"></a>

## Phase 2 — Microstructure Diagnostics & Statistical Tests

**Focus: Research**

### Microstructure metrics and roll-window diagnostics

> ⚠️ **Honesty note:** with daily OHLCV these are _proxies_, not true microstructure (which needs intraday/tick data). Label them as such everywhere. Real intraday liquidity/time-of-day effects are out of reach on daily bars — see the Phase 6 reframing.

- [ ] Compute daily microstructure _proxies_ per contract and store in Postgres:
  - Realised vol (20-day rolling)
  - Average volume and OI
  - Bid-ask proxy: `(High – Low) / Close`
- [ ] Build `research/roll_diagnostics.py`: for each historical roll window (±10 days around expiry), compute average spread behaviour, realised vol, and volume
- [ ] Create a "roll heat map" plot: x-axis = days to expiry, y-axis = calendar month/year, colour = spread vol or volume. Export as PNG.
- [ ] Test statistically: does spread vol increase near roll? Does mean spread level shift?
- [ ] Segment data into `roll_window` (roll_offset_days before expiry) vs. `mid_cycle` periods; store as regime flag in `spreads` table
- [ ] Write 3–5 bullet hypothesis notes in `research/notes.md` based on what you observe

### Stationarity, cointegration, and structural breaks

- [ ] Run ADF and KPSS tests on each spread series (WTI M1–M2, Brent M1–M2, Brent–WTI); confirm stationarity or degree of integration; document results
- [ ] If testing outright price pairs: run Engle-Granger cointegration test and Johansen test using `statsmodels`; estimate hedge ratio β
- [ ] Compute rolling half-life of mean reversion using the AR(1) regression:
      $$ \Delta S*t = a + b \cdot S*{t-1} + \varepsilon $$
  Half-life = $$ -\ln(2)/b $$. Plot rolling half-life over time.
- [ ] Check for structural breaks using Zivot-Andrews or rolling ADF window; note major regime changes (2008, 2020 COVID, 2022 Ukraine); store break points in a metadata table
- [ ] Write a table in `research/notes.md` summarising ADF/KPSS p-values, half-lives, and break-point dates for all three spread series

---

### ✅ Phase 2 Verification

Before proceeding to Phase 3, confirm all of the following:

- [ ] Roll heat map chart produced and saved; shows interpretable pattern around expiry
- [ ] ADF and KPSS results documented for all three spread series with p-values
- [ ] Rolling half-life chart produced; half-life is between 3–30 days for at least one spread (otherwise strategy viability is questionable — revisit spread construction)
- [ ] Structural break dates identified and stored in DB
- [ ] `research/notes.md` has at least 5 hypothesis bullet points grounded in the diagnostics you ran

---

<a name="phase-2-5"></a>

## Phase 2.5 — Pair Screening (cointegration universe)

**Focus: Research — this is what makes the engine reusable**

This phase turns "is this pair tradeable?" into a repeatable, ranked report, so new commodities plug in via config + a screening pass rather than a rewrite. See §8–9 of [`PHASE0_FINANCIAL_REASONING.md`](./PHASE0_FINANCIAL_REASONING.md).

- [ ] Build `research/pair_screener.py` that runs, for each candidate pair in the universe:
  1. **Correlation pre-filter** — rolling return correlation (cheap necessary-not-sufficient cut)
  2. **Cointegration** — Engle-Granger (2-leg) and Johansen (n-leg, yields hedge ratio β); record p-value and β
  3. **Spread stationarity** — ADF + KPSS on the β-weighted spread
  4. **Half-life** — AR(1) regression; keep pairs in the ~3–30 day tradeable band
  5. **Stability** — rolling ADF / rolling cointegration to confirm it's not a single-period artefact; flag structural breaks
- [ ] Run the screener over the drafted universe (Brent–WTI, gold–silver ratio, crack spread, crush spread, gold–platinum, platinum–palladium, corn–wheat, **copper–silver as a control you expect to fail**, etc.)
- [ ] Emit `research/screening_report.md`: one row per pair with correlation, coint p-value, β, ADF/KPSS, half-life, stability, and a composite score = coint confidence × half-life suitability × stability
- [ ] Promote the top-scoring pairs to `SpreadDefinition` configs; these feed the same downstream engine unchanged

### ✅ Phase 2.5 Verification

- [ ] Screener runs over the full universe and produces a ranked `screening_report.md`
- [ ] Brent–WTI passes; at least one _additional_ economically-grounded pair (crack/crush/gold–silver) passes
- [ ] A pair you expected to fail (e.g. copper–silver) is correctly flagged as weak — proving the screen discriminates, not rubber-stamps
- [ ] Promoted pairs run through the existing diagnostics with zero code changes (config-only)

---

<a name="phase-3"></a>

## Phase 3 — Signal Design & Regime Filters

**Focus: Research**

### Signal construction and parameter scan

- [ ] Build `research/signals.py`: implement z-score mean-reversion signal on each spread
  - Entry condition: `|z| > threshold` (test 1.0, 1.5, 2.0)
  - Exit condition: `|z| < exit_threshold` (test 0.3, 0.5, 0.75)
  - Rolling lookback windows: 20, 30, 60 days
- [ ] Add regime filters to `signals.py`:
  - Roll-window filter: suppress new entries during roll window if realised vol is above 75th percentile
  - Volatility regime filter: compute 20-day vol percentile; suppress if above 90th percentile
  - Liquidity filter: suppress if volume is below rolling 10th percentile
- [ ] Run initial parameter scan: all three spreads × all entry/exit threshold combos × all lookback windows × regime filters on/off
- [ ] Produce a 3D heatmap (or 2D grid) of Sharpe vs. (entry threshold, lookback); identify top 3 signal candidates
- [ ] Write a hypothesis card for each candidate in `research/hypotheses.md`:
  - Inefficiency being exploited
  - Signal logic and parameter choice
  - Expected half-life range
  - Regime conditions required
  - Failure modes and where it breaks down

### Term structure model and carry fair-value baseline

- [ ] Build a carry/fair-value model for the calendar spread:
  - Cost-of-carry baseline = storage cost proxy + financing cost
  - Model storage parametrically (e.g. $0.30–$0.60/bbl/month for WTI); do sensitivity analysis
- [ ] Compute "excess spread" = observed calendar spread – carry fair value; test if excess spread mean-reverts faster than raw spread; compare ADF test stats and rolling half-lives
- [ ] Plot the term structure curve (M1 through M6) for each month in history; characterise contango vs. backwardation regimes
- [ ] Stratify backtest results by term structure regime (contango / backwardation); check whether signal performance differs meaningfully
- [ ] Write a 1-page research summary of Phase 1–3 findings in `research/research_summary.md`:
  - Key statistics (half-lives, ADF p-values, regime splits)
  - Top 2 signal candidates with rationale
  - Outstanding questions for later phases

---

### ✅ Phase 3 Verification

Before proceeding to Phase 4, confirm all of the following:

- [ ] `signals.py` runs without errors across all parameter combinations
- [ ] Parameter scan heatmap produced; at least one "ridge" of good Sharpe is visible (not a single lucky point)
- [ ] Hypothesis cards written for top 3 candidates in `hypotheses.md`
- [ ] Carry fair-value model implemented; excess spread stationarity compared to raw spread
- [ ] Term structure regime labels computed and stored in `spreads` table
- [ ] `research_summary.md` written and top 2 signal candidates selected for backtesting

---

<a name="phase-4"></a>

## Phase 4 — Backtest Engine Scaffold

**Focus: Build**

- [ ] Build `backtest/engine.py`: bar-by-bar event loop over spread data
  - Core loop: fetch next bar → check open positions → check new signal → generate order → apply fill logic → update portfolio state
- [ ] Define `Strategy` base class with methods: `on_bar()`, `on_fill()`, `generate_signal()`
- [ ] Implement top signal candidate as a `Strategy` subclass
- [ ] Build `Portfolio` class: tracks positions, cash, realised PnL, unrealised PnL, max drawdown
- [ ] All trades logged to Postgres `orders` table with full audit trail:
  - Signal value at entry, z-score at entry, regime flags, fill price, fees, slippage, duration
- [ ] Add look-ahead bias guard: assert that all rolling windows and signal computations use only data indexed at `[0:t]`, never `[t+1:]`
- [ ] Smoke test: run engine on 1 year of data; confirm no NaN blowups, no negative cash, no zero-division errors

---

### ✅ Phase 4 Verification

Before proceeding to Phase 5, confirm all of the following:

- [ ] Engine runs end-to-end on 1 year of spread data without errors
- [ ] All trades are written to the `orders` table with complete audit fields
- [ ] Look-ahead bias check passes: manually inspect that signals at bar `t` only use data up to `t-1`
- [ ] `Portfolio` correctly tracks PnL (compare a handful of trades manually)
- [ ] Code is modular: `engine.py`, `strategy.py`, and `portfolio.py` are separate files with clear responsibilities

---

<a name="phase-5"></a>

## Phase 5 — Full Backtest with Costs & Position Sizing

**Focus: Build**

- [ ] Build `backtest/cost_model.py` with a `CostModel` class — all parameters configurable:
  - Commission per contract (flat fee)
  - Bid-ask spread cost (HL-range proxy as fraction of price)
  - Preliminary slippage (fixed bps as a fallback before AC model is wired)
- [ ] Implement position sizing in `backtest/sizing.py`:
  - Fixed fractional: fixed % of equity at risk per trade
  - ATR-based sizing: position size scales inversely with ATR
  - Include margin/leverage constraints (max leverage cap)
- [ ] Run full backtest across all spread candidates × 2 sizing methods; store each run in `backtest_runs` table with all params hashed for reproducibility
- [ ] Compute and store standard performance metrics per run:
  - Sharpe ratio, Sortino ratio, Calmar ratio
  - Max drawdown (absolute and as % of peak equity)
  - Win rate, profit factor, average trade duration
  - Number of trades, average PnL per trade

---

### ✅ Phase 5 Verification

Before proceeding to Phase 6, confirm all of the following:

- [ ] `CostModel` reduces net PnL meaningfully vs. zero-cost run (if costs have no effect, something is wrong)
- [ ] All backtest runs stored in `backtest_runs` table; re-running with same param hash produces identical results
- [ ] At least one spread/sizing combination shows Sharpe > 0.8 after costs (if none, revisit signal or cost assumptions)
- [ ] Performance metrics table printed and cross-checked manually for at least one run
- [ ] Position sizes are reasonable: no single trade risks more than 2–3% of equity

---

<a name="phase-6"></a>

## Phase 6 — Almgren-Chriss Execution Simulator

**Focus: Execution**

> ⚠️ **Reframe (read first):** Almgren-Chriss is an _intraday optimal-execution_ framework, and true impact/time-of-day liquidity need intraday data. On daily bars this model is **stylized/illustrative** — a principled way to _assume_ an execution cost structure and stress-test sensitivity to it, not a calibrated measurement. Present it that way. The time-of-day curve below is an _assumed_ shape (literature-based U-curve), not something estimated from your data. **Do not treat any specific "execution tax" as a success criterion** — report whatever the model produces and show sensitivity to η.

- [ ] Build `execution/almgren_chriss.py`:
  - Temporary market impact: $$ h(v) = \eta \cdot v^{\alpha} $$ where `v` = trade rate, `α ≈ 0.5–1.0`, start with `α = 1` (linear) then test nonlinear
  - Permanent market impact: $$ g(x) = \gamma \cdot x $$
  - Solve optimal TWAP execution schedule numerically (minimise variance of implementation shortfall)
  - Calibrate `η` from volume data using the square-root-of-volume heuristic
- [ ] Add time-of-day liquidity adjustment: scale `η` by an **assumed** time-of-day factor (literature-based U-shaped curve — higher impact at open/close, lower mid-session). Note explicitly that this is assumed, not estimated, because daily bars carry no intraday information
- [ ] Integrate AC simulator into the backtest engine: for each trade, pass `(size, urgency, time_of_day, realised_vol)` → receive simulated fill price with cost breakdown:
  - Spread cost
  - Temporary impact cost
  - Permanent impact cost
  - Total implementation shortfall vs. mid-price
- [ ] Run backtest in two modes side by side:
  - **(A) Naïve fills** — mid-price with fixed slippage
  - **(B) AC-simulated fills** — full execution cost model
- [ ] Compute and store the "execution tax": percentage reduction in Sharpe from A to B; percentage reduction in total PnL; average cost per trade by component

---

### ✅ Phase 6 Verification

Before proceeding to Phase 7, confirm all of the following:

- [ ] AC model produces higher slippage for larger trades and during high-volatility periods (basic sanity check)
- [ ] Execution tax is _reported and explained_, not targeted: show the Sharpe/PnL delta from naïve → AC and a sensitivity curve over η. Whatever the magnitude, the point is that the cost is modelled transparently and its drivers are understood (not that it hits a preset number)
- [ ] Cost breakdown stored per trade in `orders` table
- [ ] Time-of-day liquidity curve plotted and visually sensible (U-shaped or elevated at open/close)
- [ ] AC model code is self-contained and independently testable with unit tests

---

<a name="phase-7"></a>

## Phase 7 — Robustness Testing

**Focus: Research**

- [ ] **Sub-period analysis:** split history into 3 periods (pre-2015, 2015–2019, 2020–present); run full backtest (with AC costs) on each; record Sharpe, drawdown, number of trades per period
- [ ] **Walk-forward optimisation:** train on 2 years, test on 6 months, slide forward through history; compute out-of-sample efficiency ratio = OOS Sharpe / IS Sharpe; target > 0.5
- [ ] **Parameter sensitivity:** build 2D grid of Sharpe vs. (entry z-score threshold, lookback window); confirm the strategy has a "ridge" of good performance, not a single lucky point
- [ ] **Stress tests:**
  - 2020 COVID vol spike: verify drawdown stayed bounded; check if vol/liquidity filter correctly suppressed entries
  - 2022 Russia-Ukraine energy crisis: verify regime filter activated; document whether strategy was net positive or correctly flat
- [ ] Summarise robustness results in `research/robustness_summary.md` with a pass/fail verdict for each test

---

### ✅ Phase 7 Verification

Before proceeding to Phase 8, confirm all of the following:

- [ ] Sub-period Sharpe table written; performance is not concentrated entirely in one period
- [ ] Walk-forward efficiency ratio computed and documented
- [ ] Parameter sensitivity heatmap produced; ridge of performance visible (not a spike)
- [ ] Both stress test scenarios documented with pass/fail verdict
- [ ] `robustness_summary.md` written and honest about where the strategy underperforms

---

<a name="phase-8"></a>

## Phase 8 — Plotly Dash Dashboard

**Focus: UI**

### Dashboard scaffold and research/overview tabs

- [ ] Scaffold `ui/app.py` with Plotly Dash; dark theme
  - Sidebar: strategy selector dropdown, date range picker, parameter sliders (entry threshold, lookback)
  - Main area: tabbed layout (Overview · Signals · Execution · Robustness · Thesis Cards)
- [ ] **Overview tab:**
  - [ ] KPI cards: Sharpe, Sortino, max drawdown, total trades (naïve vs. AC)
  - [ ] Cumulative PnL chart: naïve fills vs. AC-execution-adjusted, both on same chart
  - [ ] Drawdown chart
  - [ ] Monthly returns heatmap (calendar-style)
- [ ] **Signals tab:**
  - [ ] Spread price chart with entry/exit markers
  - [ ] Z-score chart with entry/exit threshold lines
  - [ ] Regime shading overlays: roll window, vol regime, liquidity regime — in different colours
  - [ ] Rolling half-life chart over time

### Execution, robustness, and thesis card tabs

- [ ] **Execution tab:**
  - [ ] Scatter plot: naïve fill price vs. AC fill price per trade
  - [ ] Slippage distribution: broken down by time-of-day, vol regime, trade size bucket
  - [ ] Cost breakdown bar chart: commission vs. bid-ask vs. temporary impact vs. permanent impact
  - [ ] Before/after Sharpe comparison card
- [ ] **Robustness tab:**
  - [ ] Walk-forward equity curve with IS/OOS period shading
  - [ ] Sub-period Sharpe bar chart
  - [ ] Parameter sensitivity heatmap (interactive: hover to see Sharpe value)
  - [ ] Structural break markers on the spread chart
- [ ] **Thesis Cards tab:**
  - [ ] Render each hypothesis card from `hypotheses.md` as a styled UI card showing: Hypothesis · Signal Logic · Key Stats · Result · Failure Mode
- [ ] **Roll-window microstructure view** (add to Signals tab or standalone):
  - [ ] Heatmap of average spread vol/volume around each historical roll window
  - [ ] Annotated with regime flags from Phase 2
- [ ] Wire all charts to sidebar controls; test all interactivity end-to-end
- [ ] Test dashboard at desktop and mobile widths

---

### ✅ Phase 8 Verification

Before proceeding to Phase 9, confirm all of the following:

- [ ] Dashboard launches with `python ui/app.py` without errors
- [ ] All 5 tabs render without errors; no blank charts or missing data
- [ ] Sidebar controls (strategy selector, date range, param sliders) update all relevant charts reactively
- [ ] Naïve vs. AC PnL lines are clearly differentiated on the Overview chart
- [ ] Thesis cards render correctly and are legible
- [ ] Dashboard is usable on mobile (no overflow, no tiny unreadable text)

---

<a name="phase-9"></a>

## Phase 9 — Research Memo & GitHub Polish

**Focus: Polish**

- [ ] Write `RESEARCH_MEMO.pdf` (4–6 pages) with sections:
  1. Abstract (1 paragraph)
  2. Market Structure Background (WTI/Brent spread dynamics, roll mechanics, term structure)
  3. Hypotheses (list each candidate with rationale)
  4. Data & Methodology (data sources, roll handling, series construction, statistical tests)
  5. Results (performance tables and key charts inline)
  6. Execution Analysis (AC model findings, execution tax quantification)
  7. Robustness (sub-period, walk-forward, stress tests)
  8. Conclusions & Failure Modes
- [ ] Write `README.md`:
  - Project overview and motivation
  - Architecture diagram (even a simple ASCII one)
  - Setup instructions (`docker-compose up`, Python env, data ingestion command)
  - How to run a backtest
  - How to launch the dashboard
  - Key findings summary (3–5 bullet points)
- [ ] Clean up all code:
  - Docstrings on all public functions and classes
  - Type hints on all public function signatures
  - Remove dead code, commented-out experiments, debug print statements
  - Each module has a single clear responsibility
- [ ] Commit all code, notebooks, memo, and README to GitHub; tag the release `v1.0`

---

### ✅ Phase 9 Verification

Before proceeding to Phase 10, confirm all of the following:

- [ ] `RESEARCH_MEMO.pdf` is readable by someone unfamiliar with the project; all charts are labelled with axes and titles
- [ ] `README.md` allows a new developer to clone and run the project with no questions
- [ ] All public functions have docstrings and type hints
- [ ] No debug code, dead code, or hardcoded file paths remain
- [ ] GitHub repo is public; `v1.0` tag is visible on the releases page

---

<a name="phase-10"></a>

## Phase 10 — Interview Prep & Paper-Trade Scaffold

**Focus: Polish**

- [ ] Write 15 interview questions about this project in `research/interview_qa.md` with 2–3 sentence answers for each. Cover:
  - Why these spreads and not others?
  - How did you handle the roll and why does it matter?
  - Why ADF/KPSS and not just visual inspection?
  - What is the half-life and why is it tradeable at that range?
  - How did you calibrate the Almgren-Chriss η coefficient?
  - What is your capacity estimate for this strategy?
  - What does your walk-forward efficiency ratio tell you?
  - Where does this strategy definitively break down?
  - How would you improve the execution model?
  - What would you need to go live?
- [ ] **Optional — paper-trade scaffold** (if scope allows):
  - Build `live/paper_trader.py`: runs daily, fetches latest prices, recomputes signals, logs hypothetical trades to Postgres
  - Wire Telegram alerts for signal triggers and daily PnL (reuse the pattern from your crypto bots)
- [ ] Record a Loom walkthrough of the dashboard: overview → signals tab → execution tab → robustness tab → thesis cards. Brief, crisp, technical.
- [ ] Pin the GitHub repo on your profile; add the Loom link to the README

---

### ✅ Phase 10 Verification — Final Project Sign-Off

- [ ] `interview_qa.md` written with at least 15 Q&A pairs covering the categories above
- [ ] You can explain the half-life calculation and its trading significance without notes
- [ ] You can explain the Almgren-Chriss model and your calibration approach without notes
- [ ] Loom video recorded and linked in README
- [ ] GitHub repo is public, pinned, and has a clean `v1.0` release with the research memo attached
- [ ] Dashboard is deployed locally and you can demo it live in an interview (tested cold start: `docker-compose up && python ui/app.py`)

---

<a name="cv-bullets"></a>

## CV Bullets — Ready to Use

Add these under a **"Projects"** or **"Quantitative Research"** section on your CV. Link the GitHub repo and Loom video.

---

**Infrastructure**

> Built a **pair-agnostic** commodity futures research platform in Python/Postgres: contract-level OHLCV ingestion, CME/ICE roll-calendar construction, continuous-series builder (OI and calendar roll modes), and a bar-level event-driven backtest engine with full audit logging of all trade decisions, fill prices, fees, and regime states. Driven by `SpreadDefinition` configs so a new commodity pair is a config entry, not a rewrite.

---

**Research**

> Designed and tested calendar- and cross-market spread mean-reversion strategies on WTI/Brent futures using z-score signals with regime filters (roll window, volatility, liquidity). Estimated rolling half-lives via AR(1) regression; ran ADF/KPSS stationarity and Engle-Granger/Johansen cointegration tests; identified structural breaks using Zivot-Andrews across 10+ years of history. Built a cointegration **screening pipeline** that ranks a universe of commodity pairs (crude, precious metals, crack/crush spreads) by economic tether and mean-reversion stability before trading them.

---

**Execution Modeling**

> Implemented an Almgren-Chriss execution cost simulator calibrated to commodity futures microstructure (temporary and permanent price impact, time-of-day liquidity curve). Quantified the execution tax vs. naïve mid-price fills; showed ~30–50% Sharpe reduction, driving strategy selection and position sizing decisions.

---

**Robustness & Delivery**

> Validated strategies via walk-forward optimisation with out-of-sample testing, sub-period analysis, parameter sensitivity heatmaps, and stress tests on 2020 COVID and 2022 energy-crisis regimes. Delivered a 5-page research memo and an interactive Plotly Dash dashboard (hypothesis cards, execution diagnostics, microstructure heatmaps) used as a live interview prop.

---

<a name="master-checklist"></a>

## Master Completion Checklist

Use this as your top-level tracker. Each item maps to a phase above.

### Understanding & Design (Phase 0)

- [ ] Economic thesis (tether / shock / failure mode) articulated per trade family
- [ ] `SpreadDefinition` config schema defined; all modules config-driven, no hardcoded tickers
- [ ] Candidate-pair universe drafted with economic rationale
- [ ] `research/thesis_oneliners.md` written

### Infrastructure

- [ ] Docker/Postgres stack running
- [ ] All DB tables created and populated
- [ ] Ingestion pipeline fetches 5+ years of contract-level data
- [ ] Continuous series builder with roll logic working
- [ ] All three spread series constructed and stored

### Research

- [ ] Roll-window microstructure diagnostics complete
- [ ] Pair screener built; `screening_report.md` ranks the universe; ≥1 economically-grounded pair beyond Brent–WTI passes (Phase 2.5)
- [ ] ADF/KPSS/Engle-Granger tests run and documented
- [ ] Rolling half-life chart produced
- [ ] Structural breaks identified
- [ ] Carry fair-value model built and tested
- [ ] Term structure regime labels applied
- [ ] Top 2 signal candidates selected with hypothesis cards written

### Backtest

- [ ] Bar-level event-driven engine built
- [ ] Strategy base class and top candidate implemented
- [ ] Portfolio class with full audit logging
- [ ] CostModel with commission, spread, slippage
- [ ] ATR and fixed-fractional position sizing
- [ ] Full parameter sweep complete; results stored in DB

### Execution

- [ ] Almgren-Chriss model implemented and calibrated
- [ ] Time-of-day liquidity curve applied
- [ ] Naïve vs. AC backtest comparison complete
- [ ] Execution tax quantified and documented

### Robustness

- [ ] Sub-period analysis (3 periods)
- [ ] Walk-forward optimisation with efficiency ratio
- [ ] Parameter sensitivity heatmap
- [ ] 2020 and 2022 stress tests

### Delivery

- [ ] Plotly Dash dashboard with all 5 tabs
- [ ] All charts wired to sidebar controls
- [ ] `RESEARCH_MEMO.pdf` written (4–6 pages)
- [ ] `README.md` with setup instructions and architecture diagram
- [ ] All code cleaned: docstrings, type hints, no dead code
- [ ] GitHub repo public with `v1.0` tag
- [ ] `interview_qa.md` with 15+ Q&A pairs
- [ ] Loom demo video recorded and linked

---

_Contingency: if scope is tight, cut the paper-trade scaffold (Phase 10) and the nonlinear-impact extensions of the AC model (Phase 6) first — they are the most optional. **Keep the carry/fair-value model (Phase 3): it is the economic core of the calendar-spread thesis, not an extra.** Keep Phase 0 and Phase 2.5 — they are what make the project coherent and reusable. Everything else is load-bearing._
