# Commodity Futures Stat-Arb Engine

A pair-agnostic commodity futures statistical arbitrage research and execution platform. Built and validated on WTI/Brent crude oil spreads, then extended to any cointegrated pair through a screening pipeline. Includes microstructure diagnostics, an Almgren-Chriss execution simulator, and a Plotly Dash dashboard.

**Why this exists:** Commodity futures spreads (calendar spreads, cross-market differentials, crack spreads) are structurally mean-reverting because of physical arbitrage constraints -- refiners switch between Brent and WTI when the differential widens, storage economics cap calendar spreads, and crack margins revert to refinery economics. This project turns that economic intuition into a testable, backtested strategy with honest cost accounting and regime-aware signal filtering.

See `RESEARCH_MEMO.pdf` for the full quantitative write-up.

---

## Architecture

```
commodity-stat-arb/
|
+-- config/                  SpreadDefinition YAML configs (one file per pair)
|   +-- brent_wti.yaml       No tickers hardcoded in code -- all read from here
|   +-- wti_calendar.yaml
|   +-- brent_calendar.yaml
|   +-- schema.py            Pydantic models: LegConfig, SpreadDefinition
|   +-- loader.py            load_spread() / load_all_spreads()
|
+-- data/                    Ingestion and series construction
|   +-- providers/
|   |   +-- databento_provider.py   Fetches contract-month OHLCV via Databento API
|   |   +-- base.py                 Abstract base for OHLCV providers
|   +-- series_builder.py    Builds continuous spread series from raw contracts
|   +-- build_spreads.py     Entry point: python -m data.build_spreads
|
+-- db/                      Database layer
|   +-- models.py            SQLAlchemy ORM (8 tables)
|   +-- session.py           Engine and session factory
|   migrations/              Alembic migration scripts
|
+-- research/                Statistical analysis and signal research
|   +-- stats.py             ADF, KPSS, Engle-Granger, Johansen, half-life, ZA
|   +-- signals.py           Z-score signal generation, regime filters, backtest loop
|   +-- carry_model.py       Cost-of-carry fair value, term structure regime
|   +-- pair_screener.py     Universe screening: cointegration + composite score
|   +-- hypotheses.md        Trade hypotheses with economic rationale
|   +-- robustness_summary.md
|
+-- backtest/                Event-driven backtest engine
|   +-- engine.py            Bar-by-bar backtest with audit log
|   +-- strategy.py          ZScoreStrategy: entry/exit/filter logic
|   +-- cost_model.py        Commission + bid-ask + slippage per trade
|   +-- sizing.py            FixedFractionalSizing / ATRSizing (1% risk/trade)
|
+-- execution/               Execution cost modelling
|   +-- almgren_chriss.py    Temporary + permanent market impact model
|
+-- scripts/                 One-shot research runs
|   +-- run_phase5_sweep.py  Full parameter sweep with costs
|   +-- run_phase6_ac.py     Almgren-Chriss vs naive fills comparison
|   +-- run_phase7_robustness.py  Sub-period, walk-forward, stress tests
|
+-- ui/                      Plotly Dash dashboard
|   +-- app.py               5-tab dashboard (Overview, Signals, Execution, Robustness, Thesis)
|
+-- tests/                   Pytest unit tests
+-- docs/                    PLAN.md, financial reasoning notes
+-- docker-compose.yml       Postgres 16 + pgAdmin
+-- pyproject.toml           Python deps (managed with uv)
```

**Design principle:** Every module operates on a generic `SpreadDefinition` config object, never a hardcoded ticker. Adding a new commodity pair is a config YAML entry plus a screening pass, not a rewrite.

**Stack:** Python 3.11 + uv, PostgreSQL 16, Docker, pandas, statsmodels, scipy, SQLAlchemy, Plotly Dash, Databento API.

---

## Setup

### 1. Clone and install Python dependencies

```bash
git clone <repo-url>
cd commodity-stat-arb

# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv and install all dependencies
uv sync
```

### 2. Configure environment variables

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```
POSTGRES_USER=statarb
POSTGRES_PASSWORD=your_password
POSTGRES_DB=statarb
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

PGADMIN_EMAIL=admin@admin.com
PGADMIN_PASSWORD=your_pgadmin_password

DATABENTO_API_KEY=your_key_here
```

You need a Databento API key to ingest contract-level data. Sign up at databento.com. Historical data for crude futures (2018 onwards) costs roughly $5-20 depending on date range.

### 3. Start the database

```bash
docker-compose up -d
```

Postgres runs on port 5432. pgAdmin is available at http://localhost:5050.

### 4. Run database migrations

```bash
uv run alembic upgrade head
```

### 5. Ingest contract data

**Automated (recommended):** run both ingestion and spread-building in one command:

```bash
uv run python scripts/ingest_and_build.py
```

Scope to a single pair or date range with optional flags:

```bash
uv run python scripts/ingest_and_build.py --spread brent_wti
uv run python scripts/ingest_and_build.py --start 2020-01-01 --end 2024-12-31
```

**Manual (step by step):**

Fetch daily OHLCV bars for all configured spreads from Databento:

```bash
uv run python -m data.ingest
```

Then build the continuous spread series (stitches individual contract months into a clean spread time series):

```bash
uv run python -m data.build_spreads
```

To build only one spread:

```bash
uv run python -m data.build_spreads --spread brent_wti
```

To verify data is in the DB, open the Phase 1 verification notebook:

```bash
uv run jupyter notebook research/01_phase1_verification.ipynb
```

---

## Running a Backtest

**Automated (recommended):** run all three phases in sequence with one command:

```bash
uv run python scripts/run_all_backtests.py
```

Pass `--no-db` for a dry run that skips writing results to the database:

```bash
uv run python scripts/run_all_backtests.py --no-db
```

**Manual (step by step):**

Full parameter sweep -- all spread/signal combinations written to the `backtest_runs` table:

```bash
uv run python scripts/run_phase5_sweep.py
```

Naive fills vs Almgren-Chriss execution cost comparison:

```bash
uv run python scripts/run_phase6_ac.py
```

Robustness checks (sub-period, walk-forward, parameter sensitivity, stress tests):

```bash
uv run python scripts/run_phase7_robustness.py
```

Add `--no-db` to any individual script to skip writing results back to the database.

---

## Launching the Dashboard

```bash
uv run python ui/app.py
```

Open http://localhost:8050.

The dashboard has 5 tabs:

- **Overview** -- equity curves (naive vs AC fills), trade log, PnL attribution
- **Signals** -- z-score chart, regime overlays, roll window heatmap
- **Execution** -- Almgren-Chriss cost breakdown, capacity stress table
- **Robustness** -- sub-period table, walk-forward efficiency ratios, parameter sensitivity heatmap
- **Thesis Cards** -- one-card-per-spread summary of economic rationale and signal status

Use the sidebar to switch spreads, adjust signal parameters, and change the date range. All charts update reactively.

---

## Adding New Pairs

The platform is pair-agnostic by design. Adding a new commodity spread takes two steps.

### Step 1: Write a config YAML

Create a file in `config/` named after your pair. Use an existing file as a template:

```yaml
# config/crack_321.yaml
name: crack_321
display_name: 3-2-1 Crack Spread
spread_type: crack
legs:
  - ticker: CL=F
    provider: yfinance
    exchange: CME
    month_offset: 0
    price_multiplier: 1.0
  - ticker: RB=F
    provider: yfinance
    exchange: CME
    month_offset: 0
    price_multiplier: 42.0      # convert $/gallon to $/bbl
  - ticker: HO=F
    provider: yfinance
    exchange: CME
    month_offset: 0
    price_multiplier: 42.0
weights: [-3.0, 2.0, 1.0]
economic_tether: >
  Refining margin: 3 barrels of crude input vs 2 barrels of gasoline + 1 barrel
  of heating oil output. Physical refinery economics impose a floor and ceiling.
expected_half_life_days: 15
roll_offset_days: 5
roll_mode: calendar
```

`spread_type` can be `calendar`, `cross_market`, `crack`, `crush`, or `ratio`.
`weights` are applied as `sum(weight_i * price_i * price_multiplier_i)`.

### Step 2: Run the screening pipeline

Before committing capital to a new pair, run it through the statistical screener to confirm it passes the cointegration and half-life filters:

```bash
# Screen all pairs in the CANDIDATES list (edit research/pair_screener.py to add yours)
uv run python -m research.pair_screener

# Or run a quick check by adding a CandidatePair entry to the CANDIDATES list
# at the top of research/pair_screener.py, then re-run
```

The screener runs ADF, KPSS, Engle-Granger, Johansen, rolling half-life, and stability checks. It produces a composite score (0-1). Pairs with score >= 0.5, ADF p < 0.05, and half-life in the 3-30 day band are viable candidates.

### Step 3: Ingest data and build the spread series

```bash
# Build spread series for the new pair only
uv run python -m data.build_spreads --spread crack_321
```

### Step 4: Run the full backtest

```bash
# Runs sweep + AC comparison + robustness in one go
uv run python scripts/run_all_backtests.py
```

Results are written to the `backtest_runs` table and visible in the dashboard immediately after the run.

---

## Key Findings

See `RESEARCH_MEMO.pdf` for the full quantitative write-up with all tables and methodology.

Brief summary:

- **Brent-WTI is the primary trade.** The cross-market differential is cointegrated (Engle-Granger p=0.028), mean-reverts with a 4.9-day half-life, and produces Sharpe 0.41 after full transaction costs with a 73% win rate and 6.4x profit factor across ~8.5 years of daily data.
- **Calendar spreads need regime gates.** Brent calendar works in backwardation (Sharpe 0.32) but not contango. WTI calendar is only tradeable with a hard contango entry filter; without it Sharpe is -0.13 across the full history.
- **Walk-forward efficiency is high.** Brent-WTI OOS Sharpe exceeds IS Sharpe on average (efficiency ratio 1.37), which means the signal is not overfit to the training window.
- **Market impact is negligible at this scale.** At 2-10 contracts per trade (a $100k book), the Almgren-Chriss model puts temporary impact below $1/trade vs $10-28 in commission. The cost constraint is commission and bid-ask spread, not impact. The strategy would not hit an impact wall until above ~100 contracts per trade (approximately a $5-10M book).
- **The strategy survives stress periods.** Brent-WTI max drawdown was -4.4% during COVID and -3.5% during the 2022 energy crisis. The spread mean-reverts even in dislocated environments because the physical arbitrage tether (refinery switching) holds.
