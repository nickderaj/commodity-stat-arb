"""Plotly Dash dashboard for the commodity stat-arb engine.

Tabs: Overview | Signals | Execution | Robustness | Thesis Cards

Run from project root:
    uv run python ui/app.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash
from dash import dcc, html, Input, Output
import dash_bootstrap_components as dbc

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.cost_model import CostModel
from backtest.engine import BacktestEngine
from backtest.sizing import FixedFractionalSizing
from backtest.strategy import ZScoreStrategy
from execution.almgren_chriss import AlmgrenChrissModel
from research.signals import compute_filter_masks, compute_zscore, load_spread_df
from research.stats import rolling_half_life


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPREADS = ["brent_wti", "brent_calendar", "wti_calendar"]

SPREAD_LABELS = {
    "brent_wti": "Brent-WTI Cross-Market",
    "brent_calendar": "Brent Calendar M1-M2",
    "wti_calendar": "WTI Calendar M1-M2",
}

STRUCTURAL_BREAKS = {
    "wti_calendar": "2020-04-27",
    "brent_calendar": "2023-11-05",
    "brent_wti": "2019-05-31",
}

# Phase 7 sub-period data (hardcoded from robustness_summary.md)
_SUB_PERIOD_ROWS = [
    ("2015-2019", "brent_calendar", 0.076),
    ("2015-2019", "brent_wti",      0.841),
    ("2015-2019", "wti_calendar",  -0.054),
    ("2020+",     "brent_calendar", 0.276),
    ("2020+",     "brent_wti",      0.363),
    ("2020+",     "wti_calendar",  -0.152),
]

# Phase 7 walk-forward per-window data (brent_wti windows only, for equity chart shading)
_WF_WINDOWS = [
    ("2018-01-01", "2019-12-31", "2020-01-01", "2020-06-30", 0.841, 1.087),
    ("2020-01-01", "2021-12-31", "2022-01-01", "2022-06-30", 0.351, 0.718),
    ("2022-01-01", "2023-12-31", "2024-01-01", "2024-06-30", 0.977, 0.746),
]

# Phase 7 sensitivity grid for brent_wti (entry, lookback, sharpe)
_SENSITIVITY_ROWS = [
    (0.5,  10, 0.156), (0.5,  20, 0.330), (0.5,  30, 0.168), (0.5,  45, 0.359), (0.5,  60, 0.503), (0.5,  90, 0.406),
    (1.0,  10, 0.208), (1.0,  20, 0.357), (1.0,  30, 0.446), (1.0,  45, 0.379), (1.0,  60, 0.413), (1.0,  90, 0.469),
    (1.5,  10, 0.350), (1.5,  20, 0.690), (1.5,  30, 0.347), (1.5,  45, 0.392), (1.5,  60, 0.490), (1.5,  90, 0.498),
    (2.0,  10, 0.241), (2.0,  20, 0.463), (2.0,  30, 0.251), (2.0,  45, 0.364), (2.0,  60, 0.412), (2.0,  90, 0.441),
    (2.5,  10, 0.407), (2.5,  20, 0.503), (2.5,  30, 0.280), (2.5,  45, 0.255), (2.5,  60, 0.391), (2.5,  90, 0.471),
    (3.0,  10,   None), (3.0, 20, 0.110), (3.0,  30, 0.151), (3.0,  45, 0.097), (3.0,  60, 0.170), (3.0,  90, 0.285),
]

# Phase 7 stress test data
_STRESS_ROWS = [
    ("2020 COVID spike",           "wti_calendar",   -0.375, -0.569, "WARN"),
    ("2020 COVID spike",           "brent_calendar", -0.372, -0.080, "PASS"),
    ("2020 COVID spike",           "brent_wti",       0.180, -0.044, "PASS"),
    ("2022 Russia-Ukraine crisis", "wti_calendar",   -0.316, -0.047, "PASS"),
    ("2022 Russia-Ukraine crisis", "brent_calendar",  0.023, -0.208, "PASS"),
    ("2022 Russia-Ukraine crisis", "brent_wti",       0.686, -0.035, "PASS"),
]

# Hypothesis card data (from research/hypotheses.md)
THESIS_CARDS = [
    {
        "title": "Brent-WTI Location Spread Mean Reversion",
        "signal_logic": "60-day rolling z-score. Entry when |z| > 1.5, exit when |z| < 0.5. Vol regime filter blocks entries when 20-day spread vol is above 90th percentile.",
        "inefficiency": "Brent and WTI are close substitutes. Refiners can switch between them when the differential strays too far. Temporary dislocations arise from geopolitical events, Cushing inventory changes, or demand shocks hitting one benchmark faster than the other.",
        "key_stats": "Phase 3 Sharpe: 0.894 | Phase 5 Sharpe: 0.412 | Trades (8.5yr): 80 | Win rate: 52% | Half-life: 4.9-10.7d",
        "regime": "Any regime (cross-market spread, not term structure). Vol filter essential - raised Sharpe from 0.452 to 0.894.",
        "result": "Primary candidate. Positive Sharpe in both available sub-periods (0.841 in 2015-2019, 0.363 in 2020+). Walk-forward efficiency ratio 1.37. Best stress test performance.",
        "failure_mode": "Structural regime shifts (new pipeline/refinery capacity). Rolling mean lag after big shocks (~60 days for mean to catch up). Post-2019-05-31 regime change identified by Zivot-Andrews.",
        "color": "success",
    },
    {
        "title": "Brent Calendar Spread at Extreme Z-score",
        "signal_logic": "60-day rolling z-score. Entry when |z| > 2.0, exit when |z| < 0.75. Higher threshold than Brent-WTI to filter noisy roll-window moves.",
        "inefficiency": "The Brent M1-M2 spread is tethered by cost-of-carry arbitrage. At more than 2 standard deviations from its 60-day mean, the spread has either genuinely overshot or temporarily mispriced the roll-implied storage cost. In either case, it reverts.",
        "key_stats": "Phase 3 Sharpe: 0.229 | Trades (8.5yr): 46 | Win rate: 51% | Half-life: 7.1d (mean) | Regime split: backwardation 0.322 vs contango 0.008",
        "regime": "Backwardation preferred. Signal works 4x better in backwardation than contango. Adding a backwardation entry gate would improve risk-adjusted returns significantly.",
        "result": "Secondary candidate. Sharpe improves from 2015-2019 (0.076) to 2020+ (0.276), which is unusual for mean-reversion strategies. Walk-forward efficiency 0.92.",
        "failure_mode": "Trending energy supply shocks (2022 Ukraine): Brent went into extreme backwardation for months, trending rather than reverting. Carry model finding: excess spread has the same half-life as raw spread - fair value model gives no timing edge.",
        "color": "primary",
    },
    {
        "title": "WTI Calendar Spread Contango Mean Reversion",
        "signal_logic": "20-day rolling z-score. Entry when |z| > 1.5, exit when |z| < 0.5. Shorter lookback matches the longer 24.6-day mean half-life. Vol filter essential.",
        "inefficiency": "In contango (M1 < M2), the WTI spread is anchored by cash-and-carry arbitrage: traders buy prompt barrels, store them, and sell forward. This puts a ceiling on how negative the spread can get. The Goldman Roll (5-9 business days per month) creates recurring flow pressure.",
        "key_stats": "Phase 3 Sharpe: 0.216 | Trades (8.5yr): 125 | Win rate: 51% | Half-life: 15.5-31.3d (IQR) | Regime split: contango 0.484 vs backwardation -0.080",
        "regime": "Contango only (M1 < M2). Signal essentially does not work outside this regime. Strategy needs a contango entry gate to avoid the -0.080 backwardation Sharpe.",
        "result": "Tertiary candidate. Negative Sharpe in both sub-periods without contango gate. 56.87% max drawdown during COVID 2020 (no stop loss). Not recommended for live trading in current form.",
        "failure_mode": "Storage capacity exhaustion (April 2020: WTI went briefly negative, arb floor breaks). Regime misclassification: spread can flip from contango to backwardation mid-hold. No stop loss in current engine - open positions ride through vol spikes.",
        "color": "warning",
    },
]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict = {}


def _get_run(spread: str, entry: float, exit_thresh: float, lookback: int, use_filters: bool, use_ac: bool) -> dict:
    key = (spread, entry, exit_thresh, lookback, use_filters, use_ac)
    if key not in _cache:
        strategy = ZScoreStrategy(
            entry_threshold=entry,
            exit_threshold=exit_thresh,
            lookback=lookback,
            use_filters=use_filters,
        )
        cost_model = CostModel(commission_per_contract=2.0, spread_bps=5.0, slippage_bps=2.0)
        sizing = FixedFractionalSizing(risk_pct=0.01, max_leverage=5.0, min_atr=0.10)
        ac_model = AlmgrenChrissModel() if use_ac else None
        engine = BacktestEngine(
            strategy=strategy,
            spread_name=spread,
            initial_capital=100_000.0,
            cost_model=cost_model,
            sizing_model=sizing,
            ac_model=ac_model,
        )
        _cache[key] = engine.run(write_to_db=False)
    return _cache[key]


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

DARK_BG = "#1a1a2e"
CARD_BG = "#16213e"
GRID_COLOR = "#2a2a4a"
TEXT_COLOR = "#e0e0f0"
ACCENT = "#4cc9f0"
GREEN = "#06d6a0"
RED = "#ef476f"
ORANGE = "#ffd166"

_LAYOUT_BASE = dict(
    paper_bgcolor=DARK_BG,
    plot_bgcolor=DARK_BG,
    font=dict(color=TEXT_COLOR, family="monospace"),
    margin=dict(l=50, r=20, t=40, b=40),
    xaxis=dict(gridcolor=GRID_COLOR, zerolinecolor=GRID_COLOR),
    yaxis=dict(gridcolor=GRID_COLOR, zerolinecolor=GRID_COLOR),
)


def _base_layout(**kwargs) -> dict:
    layout = {**_LAYOUT_BASE}
    layout.update(kwargs)
    return layout


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:.3f}"


def _pct(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:.1%}"


def _kpi_card(label: str, value: str, color: str = TEXT_COLOR) -> dbc.Card:
    return dbc.Card(
        dbc.CardBody([
            html.P(label, className="text-muted mb-1", style={"fontSize": "0.75rem", "textTransform": "uppercase", "letterSpacing": "1px"}),
            html.H4(value, style={"color": color, "fontFamily": "monospace", "marginBottom": 0}),
        ]),
        style={"backgroundColor": CARD_BG, "border": f"1px solid {GRID_COLOR}"},
        className="mb-2",
    )


# ---------------------------------------------------------------------------
# App layout
# ---------------------------------------------------------------------------

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True,
)
app.title = "Commodity Stat-Arb Dashboard"


# ── Tooltip info definitions ──────────────────────────────────────────────────

_TOOLTIPS = {
    "spread": (
        "The futures pair being traded. Brent-WTI is a cross-market spread between two crude benchmarks "
        "linked by refiner substitution. Calendar spreads (Brent or WTI M1-M2) trade the same commodity "
        "at two different delivery months, anchored by cost-of-carry arbitrage."
    ),
    "date-range": (
        "Slice of history to backtest. Default is the full available range (mid-2018 to today). "
        "Narrowing to a specific period lets you inspect sub-period performance without running the "
        "full robustness suite."
    ),
    "entry": (
        "Z-score threshold to open a position. Entry fires when the spread is this many standard "
        "deviations from its rolling mean. Higher = fewer but more extreme entries: z=2.0 fires on "
        "roughly the top/bottom 5% of observations; z=1.5 fires on ~13%. Best ridge found at 1.5-2.5."
    ),
    "exit": (
        "Position closes when the z-score falls back below this value toward zero. Lower = exit earlier "
        "(less captured but shorter exposure). Default 0.75 exits when the spread is within 0.75 std of "
        "its rolling mean, before it fully normalises."
    ),
    "lookback": (
        "Trading days used for the rolling mean and standard deviation. Shorter windows (20d) react "
        "faster to regime shifts but produce noisier z-scores. Longer windows (60-90d) are more stable "
        "but lag structural breaks by weeks. The 60d default spans ~3 half-lives for brent_wti."
    ),
    "filters": (
        "Three filters that block new entries but never force an exit: "
        "(1) Roll-window filter: suppresses entries within 10 days of expiry when vol is above 75th pct. "
        "(2) Vol regime filter: suppresses when 20-day spread vol exceeds the 90th pct rolling threshold "
        "(blocks most of 2020 COVID and 2022 Ukraine spike periods). "
        "(3) Liquidity filter: suppresses when front-month volume falls below its 10th pct rolling level."
    ),
    "ac": (
        "Almgren-Chriss execution cost model. Adds temporary market impact (cost of trading quickly, "
        "proportional to participation rate^alpha) and permanent impact (price shift that persists) on top "
        "of commission and bid-ask. At current sizes (2-10 contracts), impact is under $1/trade. "
        "Becomes material at 50+ contracts vs ~500k BBL/day ADV."
    ),
}


def _info(tooltip_id: str) -> html.Span:
    return html.Span("i", id=f"info-{tooltip_id}", className="info-icon")


def _label_row(label_content, tooltip_id: str) -> html.Div:
    """Row with a label (static or dynamic) plus a hoverable info icon."""
    return html.Div(
        [label_content, _info(tooltip_id)],
        style={"display": "flex", "alignItems": "center", "marginBottom": "4px"},
    )


def _build_tooltips() -> list:
    return [
        dbc.Tooltip(_TOOLTIPS["spread"],     target="info-spread",     placement="right"),
        dbc.Tooltip(_TOOLTIPS["date-range"], target="info-date-range", placement="right"),
        dbc.Tooltip(_TOOLTIPS["entry"],      target="info-entry",      placement="right"),
        dbc.Tooltip(_TOOLTIPS["exit"],       target="info-exit",       placement="right"),
        dbc.Tooltip(_TOOLTIPS["lookback"],   target="info-lookback",   placement="right"),
        dbc.Tooltip(_TOOLTIPS["filters"],    target="info-filters",    placement="right"),
        dbc.Tooltip(_TOOLTIPS["ac"],         target="info-ac",         placement="right"),
    ]


_SB_LABEL = {"fontSize": "0.8rem", "marginBottom": 0}

sidebar = dbc.Card([
    dbc.CardBody([
        html.H6("STRATEGY", className="text-muted mb-3",
                style={"letterSpacing": "2px", "fontSize": "0.7rem"}),

        _label_row(html.Label("Spread", style=_SB_LABEL), "spread"),
        dcc.Dropdown(
            id="dd-spread",
            options=[{"label": SPREAD_LABELS[s], "value": s} for s in SPREADS],
            value="brent_wti",
            clearable=False,
            className="mb-3",
        ),

        _label_row(html.Label("Date Range", style=_SB_LABEL), "date-range"),
        dcc.DatePickerRange(
            id="date-range",
            start_date="2018-01-01",
            end_date=date.today().isoformat(),
            display_format="YYYY-MM-DD",
            className="mb-3 d-block",
        ),

        html.Hr(style={"borderColor": GRID_COLOR}),
        html.H6("SIGNAL PARAMS", className="text-muted mb-3",
                style={"letterSpacing": "2px", "fontSize": "0.7rem"}),

        _label_row(html.Label(id="label-entry", children="Entry threshold: 2.0", style=_SB_LABEL), "entry"),
        dcc.Slider(id="sl-entry", min=0.5, max=3.0, step=0.5, value=2.0,
                   marks={v: {"label": str(v), "style": {"color": "#aaa"}} for v in [0.5, 1.5, 2.5, 3.0]},
                   className="mb-3"),

        _label_row(html.Label(id="label-exit", children="Exit threshold: 0.75", style=_SB_LABEL), "exit"),
        dcc.Slider(id="sl-exit", min=0.2, max=1.0, step=0.05, value=0.75,
                   marks={v: {"label": str(v), "style": {"color": "#aaa"}} for v in [0.2, 0.5, 0.75, 1.0]},
                   className="mb-3"),

        _label_row(html.Label(id="label-lookback", children="Lookback: 60d", style=_SB_LABEL), "lookback"),
        dcc.Slider(id="sl-lookback", min=10, max=90, step=10, value=60,
                   marks={v: {"label": str(v), "style": {"color": "#aaa"}} for v in [10, 30, 60, 90]},
                   className="mb-3"),

        html.Hr(style={"borderColor": GRID_COLOR}),
        _label_row(html.Label("Regime filters", style=_SB_LABEL), "filters"),
        dbc.Switch(id="sw-filters", value=True, label="On", className="mb-3"),

        html.Hr(style={"borderColor": GRID_COLOR}),
        _label_row(html.Label("Almgren-Chriss model", style=_SB_LABEL), "ac"),
        dbc.Switch(id="sw-ac", value=True, label="On", className="mb-2"),

        html.Hr(style={"borderColor": GRID_COLOR}),
        html.Div(id="sidebar-status", style={"fontSize": "0.7rem", "color": "#888"}),

        *_build_tooltips(),
    ])
], style={"backgroundColor": CARD_BG, "border": f"1px solid {GRID_COLOR}", "height": "100%"})


tabs = dbc.Tabs([
    # ── Overview ──────────────────────────────────────────────────────────
    dbc.Tab(label="Overview", tab_id="tab-overview", children=[
        html.Div([
            dbc.Row([
                dbc.Col(html.Div(id="kpi-sharpe"), width=3),
                dbc.Col(html.Div(id="kpi-sortino"), width=3),
                dbc.Col(html.Div(id="kpi-maxdd"), width=3),
                dbc.Col(html.Div(id="kpi-trades"), width=3),
            ], className="mt-3 mb-2"),
            dbc.Row([
                dbc.Col(dcc.Graph(id="equity-chart", style={"height": "300px"}), width=8),
                dbc.Col(dcc.Graph(id="drawdown-chart", style={"height": "300px"}), width=4),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col(dcc.Graph(id="monthly-returns", style={"height": "240px"}), width=12),
            ]),
        ], className="px-3")
    ]),

    # ── Signals ───────────────────────────────────────────────────────────
    dbc.Tab(label="Signals", tab_id="tab-signals", children=[
        html.Div([
            dbc.Row([
                dbc.Col(dcc.Graph(id="spread-chart", style={"height": "280px"}), width=12),
            ], className="mt-3 mb-2"),
            dbc.Row([
                dbc.Col(dcc.Graph(id="zscore-chart", style={"height": "220px"}), width=8),
                dbc.Col(dcc.Graph(id="halflife-chart", style={"height": "220px"}), width=4),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col(dcc.Graph(id="roll-heatmap", style={"height": "240px"}), width=12),
            ]),
        ], className="px-3")
    ]),

    # ── Execution ─────────────────────────────────────────────────────────
    dbc.Tab(label="Execution", tab_id="tab-execution", children=[
        html.Div([
            dbc.Row([
                dbc.Col(dcc.Graph(id="fill-scatter", style={"height": "300px"}), width=6),
                dbc.Col(dcc.Graph(id="cost-breakdown", style={"height": "300px"}), width=6),
            ], className="mt-3 mb-2"),
            dbc.Row([
                dbc.Col(dcc.Graph(id="slippage-dist", style={"height": "260px"}), width=6),
                dbc.Col(dcc.Graph(id="sharpe-comparison", style={"height": "260px"}), width=6),
            ]),
        ], className="px-3")
    ]),

    # ── Robustness ────────────────────────────────────────────────────────
    dbc.Tab(label="Robustness", tab_id="tab-robustness", children=[
        html.Div([
            dbc.Row([
                dbc.Col(dcc.Graph(id="wf-chart", style={"height": "280px"}), width=8),
                dbc.Col(dcc.Graph(id="subperiod-chart", style={"height": "280px"}), width=4),
            ], className="mt-3 mb-2"),
            dbc.Row([
                dbc.Col(dcc.Graph(id="sensitivity-heatmap", style={"height": "280px"}), width=6),
                dbc.Col(dcc.Graph(id="stress-chart", style={"height": "280px"}), width=6),
            ]),
        ], className="px-3")
    ]),

    # ── Thesis Cards ──────────────────────────────────────────────────────
    dbc.Tab(label="Thesis Cards", tab_id="tab-thesis", children=[
        html.Div(id="thesis-cards", className="px-3 pt-3")
    ]),
], id="main-tabs", active_tab="tab-overview")


app.layout = dbc.Container([
    # Header
    dbc.Row([
        dbc.Col(html.H5("Commodity Stat-Arb Engine", style={"fontFamily": "monospace", "color": ACCENT}), width=8),
        dbc.Col(html.P("Research & Execution Platform", className="text-muted text-end mt-1", style={"fontSize": "0.8rem"}), width=4),
    ], className="py-2 border-bottom", style={"borderColor": f"{GRID_COLOR} !important"}),

    dbc.Row([
        dbc.Col(sidebar, width=2),
        dbc.Col(tabs, width=10),
    ], className="mt-2"),

    # Hidden store for results
    dcc.Store(id="results-store"),
    dcc.Store(id="spread-data-store"),
], fluid=True, style={"backgroundColor": DARK_BG, "minHeight": "100vh"})


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@app.callback(
    Output("label-entry", "children"),
    Output("label-exit", "children"),
    Output("label-lookback", "children"),
    Input("sl-entry", "value"),
    Input("sl-exit", "value"),
    Input("sl-lookback", "value"),
)
def update_slider_labels(entry, exit_thresh, lookback):
    return f"Entry threshold: {entry:.1f}", f"Exit threshold: {exit_thresh:.2f}", f"Lookback: {lookback}d"


@app.callback(
    Output("results-store", "data"),
    Output("spread-data-store", "data"),
    Output("sidebar-status", "children"),
    Input("dd-spread", "value"),
    Input("date-range", "start_date"),
    Input("date-range", "end_date"),
    Input("sl-entry", "value"),
    Input("sl-exit", "value"),
    Input("sl-lookback", "value"),
    Input("sw-filters", "value"),
    Input("sw-ac", "value"),
)
def run_backtest(spread, start_date, end_date, entry, exit_thresh, lookback, use_filters, use_ac):
    try:
        results = _get_run(spread, entry, float(exit_thresh), lookback, bool(use_filters), bool(use_ac))

        trades = results["trades"]
        trades_data = [
            {
                "entry_date": str(t.entry_date),
                "exit_date": str(t.exit_date),
                "direction": t.direction,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "fees": t.fees,
                "slippage": t.slippage,
                "spread_cost": t.spread_cost,
                "temp_impact_cost": t.temp_impact_cost,
                "perm_impact_cost": t.perm_impact_cost,
                "zscore_at_entry": t.zscore_at_entry,
                "regime_at_entry": t.regime_at_entry,
                "duration_days": t.duration_days,
            }
            for t in trades
        ]

        eq = results["equity_series"]
        results_data = {
            "sharpe": results["sharpe"],
            "sortino": results["sortino"],
            "calmar": results["calmar"],
            "max_drawdown": results["max_drawdown"],
            "total_trades": results["total_trades"],
            "win_rate": results["win_rate"],
            "profit_factor": results["profit_factor"],
            "avg_trade_pnl": results["avg_trade_pnl"],
            "realised_pnl": results["realised_pnl"],
            "equity_dates": [str(d.date()) for d in eq.index],
            "equity_values": list(eq.values),
            "trades": trades_data,
            "spread": spread,
            "start_date": start_date,
            "end_date": end_date,
        }

        df = load_spread_df(spread)
        if start_date:
            df = df[df.index >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df.index <= pd.Timestamp(end_date)]

        zscore = compute_zscore(df["value"], lookback)

        spread_data = {
            "dates": [str(d.date()) for d in df.index],
            "values": list(df["value"].fillna(float("nan"))),
            "regime": list(df["regime"].fillna("mid_cycle")),
            "ts_regime": list(df.get("ts_regime", pd.Series("", index=df.index)).fillna("")),
            "roll_flag": [bool(v) for v in df["roll_window_flag"].fillna(False)],
            "zscore": [float(z) if not np.isnan(z) else None for z in zscore],
        }

        status = f"Run complete: {results['total_trades']} trades | Sharpe {_fmt(results['sharpe'])}"
        return results_data, spread_data, status

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return {}, {}, f"Error: {exc}"


# ── Overview tab callbacks ─────────────────────────────────────────────────

@app.callback(
    Output("kpi-sharpe", "children"),
    Output("kpi-sortino", "children"),
    Output("kpi-maxdd", "children"),
    Output("kpi-trades", "children"),
    Input("results-store", "data"),
)
def update_kpis(data):
    if not data:
        return [_kpi_card("Sharpe", "—")] * 4
    sharpe = data.get("sharpe")
    sortino = data.get("sortino")
    maxdd = data.get("max_drawdown")
    trades = data.get("total_trades", 0)

    sharpe_color = GREEN if sharpe and sharpe > 0.5 else (ORANGE if sharpe and sharpe > 0 else RED)
    dd_color = GREEN if maxdd and maxdd > -0.1 else (ORANGE if maxdd and maxdd > -0.2 else RED)

    return (
        _kpi_card("Sharpe", _fmt(sharpe), sharpe_color),
        _kpi_card("Sortino", _fmt(sortino)),
        _kpi_card("Max Drawdown", _pct(maxdd), dd_color),
        _kpi_card("Trades", str(trades)),
    )


@app.callback(
    Output("equity-chart", "figure"),
    Input("results-store", "data"),
    Input("sw-ac", "value"),
)
def update_equity_chart(data, use_ac):
    if not data or not data.get("equity_dates"):
        return go.Figure(layout=_base_layout(title="Cumulative PnL"))

    dates = pd.to_datetime(data["equity_dates"])
    equity = np.array(data["equity_values"])
    trades = data.get("trades", [])
    initial = 100_000.0

    # Naive equity = add back AC impact costs from each trade
    ac_costs = np.zeros(len(equity))
    if use_ac and trades:
        cumulative_ac = 0.0
        eq_date_set = {d: i for i, d in enumerate(data["equity_dates"])}
        for t in trades:
            cost = t.get("temp_impact_cost", 0.0) + t.get("perm_impact_cost", 0.0)
            if cost and t.get("exit_date") in eq_date_set:
                idx = eq_date_set[t["exit_date"]]
                ac_costs[idx:] += cost
    naive_equity = equity + ac_costs

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=naive_equity,
        name="Naive fills",
        line=dict(color=ACCENT, width=1.5),
        hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra>Naive</extra>",
    ))
    if use_ac and np.any(ac_costs != 0):
        fig.add_trace(go.Scatter(
            x=dates, y=equity,
            name="AC-adjusted",
            line=dict(color=ORANGE, width=1.5, dash="dash"),
            hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra>AC</extra>",
        ))
    fig.add_hline(y=initial, line=dict(color=GRID_COLOR, dash="dot", width=1))

    # Add structural break marker
    spread = data.get("spread", "brent_wti")
    brk = STRUCTURAL_BREAKS.get(spread)
    if brk:
        fig.add_vline(x=brk, line=dict(color=RED, dash="dash", width=1),
                      annotation_text="Break", annotation_font_color=RED)

    fig.update_layout(**_base_layout(
        title="Cumulative PnL - Naive vs AC-Adjusted",
        yaxis_title="Portfolio Equity ($)",
        legend=dict(bgcolor="rgba(0,0,0,0)", x=0.01, y=0.99),
    ))
    return fig


@app.callback(
    Output("drawdown-chart", "figure"),
    Input("results-store", "data"),
)
def update_drawdown_chart(data):
    if not data or not data.get("equity_dates"):
        return go.Figure(layout=_base_layout(title="Drawdown"))

    dates = pd.to_datetime(data["equity_dates"])
    equity = pd.Series(data["equity_values"], index=dates)
    peak = equity.cummax()
    dd = (equity - peak) / peak.replace(0, np.nan)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=dd * 100,
        fill="tozeroy",
        fillcolor=f"rgba(239,71,111,0.2)",
        line=dict(color=RED, width=1),
        name="Drawdown",
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.1f}%<extra></extra>",
    ))
    fig.update_layout(**_base_layout(
        title="Drawdown (%)",
        yaxis_title="%",
        yaxis_ticksuffix="%",
    ))
    return fig


@app.callback(
    Output("monthly-returns", "figure"),
    Input("results-store", "data"),
)
def update_monthly_returns(data):
    if not data or not data.get("equity_dates"):
        return go.Figure(layout=_base_layout(title="Monthly Returns"))

    dates = pd.to_datetime(data["equity_dates"])
    equity = pd.Series(data["equity_values"], index=dates)
    monthly = equity.resample("ME").last().pct_change().dropna() * 100

    if monthly.empty:
        return go.Figure(layout=_base_layout(title="Monthly Returns"))

    monthly_df = pd.DataFrame({"date": monthly.index, "ret": monthly.values})
    monthly_df["year"] = monthly_df["date"].dt.year
    monthly_df["month"] = monthly_df["date"].dt.month
    pivot = monthly_df.pivot(index="year", columns="month", values="ret")

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    cols = [month_names[m - 1] for m in pivot.columns]
    z = pivot.values
    text = [[f"{v:.1f}%" if not np.isnan(v) else "" for v in row] for row in z]

    fig = go.Figure(go.Heatmap(
        z=z,
        x=cols,
        y=[str(y) for y in pivot.index],
        text=text,
        texttemplate="%{text}",
        colorscale=[[0, RED], [0.5, DARK_BG], [1, GREEN]],
        zmid=0,
        showscale=False,
        hovertemplate="Year %{y} %{x}: %{z:.1f}%<extra></extra>",
    ))
    fig.update_layout(**_base_layout(
        title="Monthly Returns Heatmap (%)",
        margin=dict(l=50, r=20, t=40, b=30),
    ))
    return fig


# ── Signals tab callbacks ──────────────────────────────────────────────────

@app.callback(
    Output("spread-chart", "figure"),
    Input("spread-data-store", "data"),
    Input("results-store", "data"),
)
def update_spread_chart(spread_data, results_data):
    if not spread_data or not spread_data.get("dates"):
        return go.Figure(layout=_base_layout(title="Spread Price"))

    dates = pd.to_datetime(spread_data["dates"])
    values = spread_data["values"]
    regimes = spread_data["regime"]
    roll_flags = spread_data["roll_flag"]

    fig = go.Figure()

    # Regime shading - roll windows
    roll_start = None
    for i, (d, rf) in enumerate(zip(dates, roll_flags)):
        if rf and roll_start is None:
            roll_start = d
        elif not rf and roll_start is not None:
            fig.add_vrect(x0=roll_start, x1=d, fillcolor=ORANGE, opacity=0.08, line_width=0)
            roll_start = None

    # Vol regime shading (mark via ts_regime for calendar spreads)
    ts_regimes = spread_data.get("ts_regime", [])
    if ts_regimes and any(r == "backwardation" for r in ts_regimes):
        back_start = None
        for d, tsr in zip(dates, ts_regimes):
            if tsr == "backwardation" and back_start is None:
                back_start = d
            elif tsr != "backwardation" and back_start is not None:
                fig.add_vrect(x0=back_start, x1=d, fillcolor=RED, opacity=0.06, line_width=0)
                back_start = None

    # Main spread line
    fig.add_trace(go.Scatter(
        x=dates, y=values,
        name="Spread",
        line=dict(color=ACCENT, width=1),
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.3f}<extra>Spread</extra>",
    ))

    # Entry/exit markers from trades
    trades = (results_data or {}).get("trades", [])
    entry_long_x, entry_long_y = [], []
    entry_short_x, entry_short_y = [], []
    exit_x, exit_y = [], []

    for t in trades:
        ed = t["entry_date"]
        xd = t["exit_date"]
        # Find spread value at those dates
        for i, d in enumerate(spread_data["dates"]):
            if d == ed:
                if t["direction"] == 1:
                    entry_long_x.append(d)
                    entry_long_y.append(values[i])
                else:
                    entry_short_x.append(d)
                    entry_short_y.append(values[i])
            if d == xd:
                exit_x.append(d)
                exit_y.append(values[i])

    if entry_long_x:
        fig.add_trace(go.Scatter(x=entry_long_x, y=entry_long_y, mode="markers",
                                  marker=dict(color=GREEN, size=7, symbol="triangle-up"),
                                  name="Long entry", hovertemplate="%{x|%Y-%m-%d}<extra>Long entry</extra>"))
    if entry_short_x:
        fig.add_trace(go.Scatter(x=entry_short_x, y=entry_short_y, mode="markers",
                                  marker=dict(color=RED, size=7, symbol="triangle-down"),
                                  name="Short entry", hovertemplate="%{x|%Y-%m-%d}<extra>Short entry</extra>"))
    if exit_x:
        fig.add_trace(go.Scatter(x=exit_x, y=exit_y, mode="markers",
                                  marker=dict(color=TEXT_COLOR, size=5, symbol="x"),
                                  name="Exit", hovertemplate="%{x|%Y-%m-%d}<extra>Exit</extra>"))

    spread_name = (results_data or {}).get("spread", "brent_wti")
    brk = STRUCTURAL_BREAKS.get(spread_name)
    if brk:
        fig.add_vline(x=brk, line=dict(color=RED, dash="dash", width=1))

    # Custom legend for regime shading
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
                              marker=dict(color=ORANGE, opacity=0.5, size=10, symbol="square"),
                              name="Roll window"))

    fig.update_layout(**_base_layout(
        title="Spread Price with Entry/Exit Signals",
        yaxis_title="Spread ($/bbl)",
        legend=dict(bgcolor="rgba(0,0,0,0)", x=0.01, y=0.99, orientation="h"),
    ))
    return fig


@app.callback(
    Output("zscore-chart", "figure"),
    Input("spread-data-store", "data"),
    Input("sl-entry", "value"),
    Input("sl-exit", "value"),
)
def update_zscore_chart(spread_data, entry, exit_thresh):
    if not spread_data or not spread_data.get("dates"):
        return go.Figure(layout=_base_layout(title="Z-Score"))

    dates = pd.to_datetime(spread_data["dates"])
    zscores = spread_data.get("zscore", [])
    if not zscores:
        return go.Figure(layout=_base_layout(title="Z-Score"))

    zs = [z if z is not None else float("nan") for z in zscores]

    fig = go.Figure()
    fig.add_hline(y=entry, line=dict(color=RED, dash="dash", width=1.5))
    fig.add_hline(y=-entry, line=dict(color=GREEN, dash="dash", width=1.5))
    fig.add_hline(y=exit_thresh, line=dict(color=ORANGE, dash="dot", width=1.5),
                  annotation_text=f"Exit {exit_thresh:.2f}", annotation_position="right",
                  annotation_font=dict(color=ORANGE, size=9))
    fig.add_hline(y=-exit_thresh, line=dict(color=ORANGE, dash="dot", width=1.5),
                  annotation_text=f"Exit -{exit_thresh:.2f}", annotation_position="right",
                  annotation_font=dict(color=ORANGE, size=9))
    fig.add_hline(y=0, line=dict(color=GRID_COLOR, width=1))

    # Colour z-score segments: red for short signal, green for long, neutral otherwise
    fig.add_trace(go.Scatter(
        x=dates, y=zs,
        name="Z-Score",
        line=dict(color=ACCENT, width=1),
        hovertemplate="%{x|%Y-%m-%d}<br>z=%{y:.2f}<extra></extra>",
    ))

    fig.update_layout(**_base_layout(
        title="Rolling Z-Score",
        yaxis_title="Z-Score (std devs)",
    ))
    return fig


@app.callback(
    Output("halflife-chart", "figure"),
    Input("dd-spread", "value"),
)
def update_halflife_chart(spread):
    try:
        df = load_spread_df(spread)
        hl_df = rolling_half_life(df["value"].dropna(), window=252, step=21)
        hl_df = hl_df[hl_df["half_life"].notna() & (hl_df["half_life"] > 0) & (hl_df["half_life"] < 90)]
        if hl_df.empty:
            raise ValueError("no half-life data")
    except Exception:
        return go.Figure(layout=_base_layout(title="Rolling Half-Life"))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hl_df.index, y=hl_df["half_life"],
        name="Half-life",
        line=dict(color=ORANGE, width=1.5),
        fill="tozeroy",
        fillcolor="rgba(255,209,102,0.1)",
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.1f}d<extra></extra>",
    ))
    fig.add_hline(y=30, line=dict(color=RED, dash="dot", width=1),
                  annotation_text="30d", annotation_font_color=RED, annotation_font_size=9)
    fig.add_hline(y=3, line=dict(color=GREEN, dash="dot", width=1),
                  annotation_text="3d", annotation_font_color=GREEN, annotation_font_size=9)

    fig.update_layout(**_base_layout(
        title="Rolling Half-Life (252-day AR(1))",
        yaxis_title="Half-Life (days)",
    ))
    return fig


@app.callback(
    Output("roll-heatmap", "figure"),
    Input("dd-spread", "value"),
)
def update_roll_heatmap(spread):
    try:
        from db.session import get_session
        from sqlalchemy import text

        session = get_session()
        try:
            rows = session.execute(
                text("SELECT date, value, regime FROM spreads WHERE spread_name = :name ORDER BY date"),
                {"name": spread},
            ).fetchall()
            roll_rows = session.execute(
                text("SELECT expiry FROM roll_calendar WHERE product = :prod ORDER BY expiry"),
                {"prod": "CL" if "wti" in spread else "BZ"},
            ).fetchall()
        finally:
            session.close()

        if not rows or not roll_rows:
            raise ValueError("no data")

        df = pd.DataFrame(rows, columns=["date", "value", "regime"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        df["daily_change"] = df["value"].diff().abs()

        expiries = pd.to_datetime([r[0] for r in roll_rows])
        dte_list = []
        for d in df.index:
            future = expiries[expiries >= d]
            dte = (future[0] - d).days if len(future) > 0 else np.nan
            dte_list.append(min(dte, 30) if not np.isnan(dte) else np.nan)
        df["dte"] = dte_list

        df["dte_bucket"] = pd.cut(df["dte"], bins=[-1, 3, 7, 14, 21, 30],
                                   labels=["0-3", "4-7", "8-14", "15-21", "22-30"])
        df["expiry_label"] = pd.DatetimeIndex([
            expiries[expiries >= d][0] if len(expiries[expiries >= d]) > 0 else pd.NaT
            for d in df.index
        ]).strftime("%Y-%m")

        pivot = df.groupby(["expiry_label", "dte_bucket"])["daily_change"].mean().unstack("dte_bucket")
        pivot = pivot.dropna(how="all").tail(24)

        fig = go.Figure(go.Heatmap(
            z=pivot.values,
            x=[str(c) for c in pivot.columns],
            y=list(pivot.index),
            colorscale=[[0, DARK_BG], [1, ORANGE]],
            showscale=True,
            colorbar=dict(thickness=10, tickfont=dict(color=TEXT_COLOR)),
            hovertemplate="Expiry %{y}, DTE %{x}d<br>Avg |change|: %{z:.3f}<extra></extra>",
        ))
        fig.update_layout(**_base_layout(
            title="Roll Heatmap - Avg |Daily Spread Change| by DTE (days to expiry)",
            xaxis_title="Days to Expiry",
            yaxis_title="Contract Expiry",
            margin=dict(l=80, r=60, t=40, b=40),
        ))
        return fig

    except Exception:
        return go.Figure(layout=_base_layout(title="Roll Heatmap (no data)"))


# ── Execution tab callbacks ────────────────────────────────────────────────

@app.callback(
    Output("fill-scatter", "figure"),
    Input("results-store", "data"),
    Input("sw-ac", "value"),
)
def update_fill_scatter(data, use_ac):
    if not data or not data.get("trades"):
        return go.Figure(layout=_base_layout(title="Naive vs AC Fill Price"))

    trades = data["trades"]
    if not trades:
        return go.Figure(layout=_base_layout(title="Naive vs AC Fill Price"))

    naive_prices = []
    ac_prices = []
    pnls = []
    labels = []

    for t in trades:
        exit_p = t["exit_price"]
        ac_adj = t.get("temp_impact_cost", 0.0) + t.get("perm_impact_cost", 0.0)
        qty = 1  # simplified
        naive_prices.append(exit_p)
        # AC effective exit = exit_price + total_impact/quantity (impact reduces effective price received)
        ac_prices.append(exit_p + ac_adj * t["direction"])
        pnls.append(t["pnl"])
        labels.append(f"Entry: {t['entry_date']}<br>Exit: {t['exit_date']}<br>PnL: ${t['pnl']:.0f}")

    color = [GREEN if p > 0 else RED for p in pnls]

    fig = go.Figure()
    # Identity line
    mn = min(min(naive_prices), min(ac_prices))
    mx = max(max(naive_prices), max(ac_prices))
    fig.add_trace(go.Scatter(x=[mn, mx], y=[mn, mx], mode="lines",
                              line=dict(color=GRID_COLOR, dash="dot"), name="No impact"))
    fig.add_trace(go.Scatter(
        x=naive_prices, y=ac_prices,
        mode="markers",
        marker=dict(color=color, size=7, opacity=0.8),
        text=labels,
        hovertemplate="%{text}<extra></extra>",
        name="Trades",
    ))
    fig.update_layout(**_base_layout(
        title="Naive vs AC-Adjusted Fill Price",
        xaxis_title="Naive Fill Price ($/bbl)",
        yaxis_title="AC Fill Price ($/bbl)",
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    ))
    return fig


@app.callback(
    Output("cost-breakdown", "figure"),
    Input("results-store", "data"),
)
def update_cost_breakdown(data):
    if not data or not data.get("trades"):
        return go.Figure(layout=_base_layout(title="Cost Breakdown"))

    trades = data["trades"]
    if not trades:
        return go.Figure(layout=_base_layout(title="Cost Breakdown"))

    avg_fees = np.mean([t.get("fees", 0) for t in trades])
    avg_spread = np.mean([t.get("spread_cost", 0) for t in trades])
    avg_slip = np.mean([t.get("slippage", 0) for t in trades])
    avg_temp = np.mean([t.get("temp_impact_cost", 0) for t in trades])
    avg_perm = np.mean([t.get("perm_impact_cost", 0) for t in trades])

    categories = ["Commission", "Bid-Ask Spread", "Slippage", "Temp Impact", "Perm Impact"]
    values = [avg_fees, avg_spread, avg_slip, avg_temp, avg_perm]
    colors = [ACCENT, ORANGE, ORANGE, RED, RED]

    fig = go.Figure(go.Bar(
        y=categories,
        x=values,
        orientation="h",
        marker_color=colors,
        hovertemplate="%{y}: $%{x:.2f}<extra></extra>",
        text=[f"${v:.2f}" for v in values],
        textposition="outside",
        textfont=dict(color=TEXT_COLOR, size=10),
    ))
    fig.update_layout(**_base_layout(
        title="Avg Cost per Trade Breakdown",
        xaxis_title="Average Cost per Trade ($)",
        yaxis=dict(gridcolor=GRID_COLOR, zerolinecolor=GRID_COLOR),
        margin=dict(l=100, r=60, t=40, b=40),
    ))
    return fig


@app.callback(
    Output("slippage-dist", "figure"),
    Input("results-store", "data"),
)
def update_slippage_dist(data):
    if not data or not data.get("trades"):
        return go.Figure(layout=_base_layout(title="Slippage Distribution"))

    trades = data["trades"]
    if not trades:
        return go.Figure(layout=_base_layout(title="Slippage Distribution"))

    total_slippage = [
        t.get("slippage", 0) + t.get("spread_cost", 0) + t.get("temp_impact_cost", 0) + t.get("perm_impact_cost", 0)
        for t in trades
    ]

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=total_slippage,
        nbinsx=20,
        marker_color=ACCENT,
        opacity=0.8,
        name="Total execution cost",
        hovertemplate="Cost $%{x:.2f}: %{y} trades<extra></extra>",
    ))
    fig.update_layout(**_base_layout(
        title="Total Execution Cost Distribution",
        xaxis_title="Total Cost per Trade ($)",
        yaxis_title="Count",
    ))
    return fig


@app.callback(
    Output("sharpe-comparison", "figure"),
    Input("results-store", "data"),
    Input("dd-spread", "value"),
    Input("sl-entry", "value"),
    Input("sl-exit", "value"),
    Input("sl-lookback", "value"),
    Input("sw-filters", "value"),
)
def update_sharpe_comparison(data, spread, entry, exit_thresh, lookback, use_filters):
    if not data:
        return go.Figure(layout=_base_layout(title="Before/After Sharpe"))

    try:
        naive_run = _get_run(spread, entry, float(exit_thresh), lookback, bool(use_filters), use_ac=False)
        ac_run = _get_run(spread, entry, float(exit_thresh), lookback, bool(use_filters), use_ac=True)
        sharpes = [naive_run.get("sharpe", 0), ac_run.get("sharpe", 0)]
        labels = ["Naive Fills", "AC-Adjusted"]
        delta = sharpes[1] - sharpes[0] if all(s is not None for s in sharpes) else 0
    except Exception:
        sharpes = [data.get("sharpe", 0), data.get("sharpe", 0)]
        labels = ["Naive Fills", "AC-Adjusted"]
        delta = 0

    colors = [GREEN if s > 0.5 else (ORANGE if s > 0 else RED) for s in sharpes]

    fig = go.Figure(go.Bar(
        x=labels, y=[s or 0 for s in sharpes],
        marker_color=colors,
        text=[_fmt(s) for s in sharpes],
        textposition="outside",
        textfont=dict(color=TEXT_COLOR),
        hovertemplate="%{x}: Sharpe %{y:.3f}<extra></extra>",
    ))
    fig.add_annotation(
        x=0.5, y=0.05, xref="paper", yref="paper",
        text=f"Execution tax: {_fmt(delta)} Sharpe points",
        showarrow=False,
        font=dict(color=ORANGE, size=11),
    )
    fig.update_layout(**_base_layout(
        title="Naive vs AC-Adjusted Sharpe",
        yaxis_title="Sharpe Ratio",
        yaxis_range=[-0.5, max(1.0, max(s or 0 for s in sharpes) * 1.3)],
    ))
    return fig


# ── Robustness tab callbacks ───────────────────────────────────────────────

@app.callback(
    Output("wf-chart", "figure"),
    Input("results-store", "data"),
    Input("dd-spread", "value"),
)
def update_wf_chart(data, spread):
    # Show full equity curve with OOS period shading for brent_wti windows
    if not data or not data.get("equity_dates"):
        return go.Figure(layout=_base_layout(title="Walk-Forward Equity Curve"))

    dates = pd.to_datetime(data["equity_dates"])
    equity = data["equity_values"]

    fig = go.Figure()

    # OOS period shading (fixed brent_wti windows shown regardless of spread selection)
    for ts, te, os, oe, is_sharpe, oos_sharpe in _WF_WINDOWS:
        fig.add_vrect(
            x0=os, x1=oe,
            fillcolor=ACCENT, opacity=0.06, line_width=0,
            annotation_text=f"OOS {oos_sharpe:.2f}",
            annotation_position="top left",
            annotation_font=dict(color=ACCENT, size=9),
        )

    fig.add_trace(go.Scatter(
        x=dates, y=equity,
        name="Equity",
        line=dict(color=GREEN, width=1.5),
        hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
                              marker=dict(color=ACCENT, opacity=0.4, size=10, symbol="square"),
                              name="OOS periods (brent_wti WF)"))

    fig.update_layout(**_base_layout(
        title="Equity Curve with Walk-Forward OOS Periods (brent_wti baseline)",
        yaxis_title="Equity ($)",
        legend=dict(bgcolor="rgba(0,0,0,0)", x=0.01, y=0.99),
    ))
    return fig


_SUB_PERIODS = [
    ("2015-2019", "2015-01-01", "2019-12-31"),
    ("2020+",     "2020-01-01", "2026-12-31"),
]


@app.callback(
    Output("subperiod-chart", "figure"),
    Input("dd-spread", "value"),
    Input("sl-entry", "value"),
    Input("sl-exit", "value"),
    Input("sl-lookback", "value"),
    Input("sw-filters", "value"),
)
def update_subperiod_chart(spread, entry, exit_thresh, lookback, use_filters):
    rows = []
    for label, start, end in _SUB_PERIODS:
        try:
            res = _get_run(spread, entry, float(exit_thresh), lookback, bool(use_filters), use_ac=False)
            # Re-run for this specific date window (not cached - different date range)
            from backtest.strategy import ZScoreStrategy
            from backtest.cost_model import CostModel
            from backtest.sizing import FixedFractionalSizing
            strategy = ZScoreStrategy(
                entry_threshold=entry,
                exit_threshold=float(exit_thresh),
                lookback=lookback,
                use_filters=bool(use_filters),
            )
            from backtest.engine import BacktestEngine
            engine = BacktestEngine(
                strategy=strategy,
                spread_name=spread,
                initial_capital=100_000.0,
                cost_model=CostModel(commission_per_contract=2.0, spread_bps=5.0, slippage_bps=2.0),
                sizing_model=FixedFractionalSizing(risk_pct=0.01, max_leverage=5.0, min_atr=0.10),
            )
            r = engine.run(start_date=start, end_date=end, write_to_db=False)
            sharpe = r["sharpe"]
        except Exception:
            sharpe = float("nan")
        rows.append({"period": label, "sharpe": sharpe})

    periods = [r["period"] for r in rows]
    sharpes = [r["sharpe"] for r in rows]
    colors = [GREEN if (s and not np.isnan(s) and s > 0) else RED for s in sharpes]

    fig = go.Figure(go.Bar(
        x=periods,
        y=[s if (s and not np.isnan(s)) else 0 for s in sharpes],
        marker_color=colors,
        text=[_fmt(s) for s in sharpes],
        textposition="outside",
        textfont=dict(color=TEXT_COLOR),
        hovertemplate="Period: %{x}<br>Sharpe: %{y:.3f}<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color=GRID_COLOR, width=1))
    fig.update_layout(**_base_layout(
        title=f"Sub-Period Sharpe - {SPREAD_LABELS.get(spread, spread)}",
        yaxis_title="Sharpe Ratio",
        margin=dict(l=50, r=20, t=40, b=40),
    ))
    return fig


@app.callback(
    Output("sensitivity-heatmap", "figure"),
    Input("dd-spread", "value"),
)
def update_sensitivity_heatmap(spread):
    df = pd.DataFrame(_SENSITIVITY_ROWS, columns=["entry", "lookback", "sharpe"])
    pivot = df.pivot(index="entry", columns="lookback", values="sharpe")

    z = pivot.values.astype(float)
    z_text = [[f"{v:.2f}" if not np.isnan(v) else "N/A" for v in row] for row in z]

    fig = go.Figure(go.Heatmap(
        z=z,
        x=[str(c) for c in pivot.columns],
        y=[str(r) for r in pivot.index],
        text=z_text,
        texttemplate="%{text}",
        colorscale=[[0, RED], [0.35, DARK_BG], [1, GREEN]],
        zmid=0.3,
        showscale=True,
        colorbar=dict(thickness=10, tickfont=dict(color=TEXT_COLOR)),
        hovertemplate="Entry %{y}, Lookback %{x}d<br>Sharpe: %{z:.3f}<extra>brent_wti</extra>",
    ))
    fig.update_layout(**_base_layout(
        title="Parameter Sensitivity Heatmap (brent_wti)",
        xaxis_title="Lookback Window (days)",
        yaxis_title="Entry Threshold (z-score)",
        margin=dict(l=60, r=60, t=40, b=50),
    ))
    return fig


_STRESS_WINDOWS = [
    ("COVID 2020",    "2019-10-01", "2021-03-31"),
    ("Ukraine 2022",  "2021-10-01", "2023-03-31"),
]


@app.callback(
    Output("stress-chart", "figure"),
    Input("dd-spread", "value"),
    Input("sl-entry", "value"),
    Input("sl-exit", "value"),
    Input("sl-lookback", "value"),
    Input("sw-filters", "value"),
)
def update_stress_chart(spread, entry, exit_thresh, lookback, use_filters):
    from backtest.strategy import ZScoreStrategy
    from backtest.cost_model import CostModel
    from backtest.sizing import FixedFractionalSizing
    from backtest.engine import BacktestEngine

    scenarios, sharpes, max_dds = [], [], []
    for label, start, end in _STRESS_WINDOWS:
        try:
            strategy = ZScoreStrategy(
                entry_threshold=entry,
                exit_threshold=float(exit_thresh),
                lookback=lookback,
                use_filters=bool(use_filters),
            )
            engine = BacktestEngine(
                strategy=strategy,
                spread_name=spread,
                initial_capital=100_000.0,
                cost_model=CostModel(commission_per_contract=2.0, spread_bps=5.0, slippage_bps=2.0),
                sizing_model=FixedFractionalSizing(risk_pct=0.01, max_leverage=5.0, min_atr=0.10),
            )
            r = engine.run(start_date=start, end_date=end, write_to_db=False)
            sharpes.append(r["sharpe"] if not np.isnan(r["sharpe"] or 0) else 0.0)
            max_dds.append(r["max_drawdown"] if not np.isnan(r["max_drawdown"] or 0) else 0.0)
        except Exception:
            sharpes.append(0.0)
            max_dds.append(0.0)
        scenarios.append(label)

    colors_s = [GREEN if s > 0 else RED for s in sharpes]
    colors_d = [GREEN if d > -0.1 else (ORANGE if d > -0.2 else RED) for d in max_dds]

    fig = make_subplots(rows=1, cols=2,
                        subplot_titles=["Sharpe During Crisis", "Max Drawdown During Crisis"])

    fig.add_trace(go.Bar(
        x=scenarios, y=sharpes,
        marker_color=colors_s,
        text=[f"{v:.3f}" for v in sharpes],
        textposition="outside",
        textfont=dict(color=TEXT_COLOR, size=9),
        hovertemplate="%{x}<br>Sharpe: %{y:.3f}<extra></extra>",
        showlegend=False,
    ), row=1, col=1)

    fig.add_trace(go.Bar(
        x=scenarios, y=[d * 100 for d in max_dds],
        marker_color=colors_d,
        text=[f"{d*100:.1f}%" for d in max_dds],
        textposition="outside",
        textfont=dict(color=TEXT_COLOR, size=9),
        hovertemplate="%{x}<br>Max DD: %{y:.1f}%<extra></extra>",
        showlegend=False,
    ), row=1, col=2)

    fig.update_layout(
        paper_bgcolor=DARK_BG,
        plot_bgcolor=DARK_BG,
        font=dict(color=TEXT_COLOR, family="monospace"),
        margin=dict(l=40, r=20, t=60, b=80),
        title=f"Stress Tests - {SPREAD_LABELS.get(spread, spread)}",
        title_font=dict(color=TEXT_COLOR),
    )
    for ax in ["xaxis", "xaxis2", "yaxis", "yaxis2"]:
        fig.update_layout(**{ax: dict(gridcolor=GRID_COLOR, zerolinecolor=GRID_COLOR)})
    fig.update_xaxes(tickangle=-20, tickfont=dict(size=9))

    return fig


# ── Thesis Cards tab ───────────────────────────────────────────────────────

@app.callback(
    Output("thesis-cards", "children"),
    Input("main-tabs", "active_tab"),
)
def render_thesis_cards(active_tab):
    if active_tab != "tab-thesis":
        return []

    cards = []
    for card in THESIS_CARDS:
        cards.append(
            dbc.Card([
                dbc.CardHeader(
                    html.H5(card["title"], className="mb-0", style={"fontFamily": "monospace"}),
                    style={"backgroundColor": CARD_BG, "borderColor": GRID_COLOR}
                ),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.P([html.Strong("Inefficiency: "), card["inefficiency"]], className="mb-2 small"),
                            html.P([html.Strong("Signal Logic: "), card["signal_logic"]], className="mb-2 small"),
                            html.P([html.Strong("Regime Required: "), card["regime"]], className="mb-2 small"),
                        ], width=6),
                        dbc.Col([
                            html.P([html.Strong("Key Stats: "), card["key_stats"]], className="mb-2 small"),
                            html.P([html.Strong("Result: "), card["result"]], className="mb-2 small"),
                            html.P([html.Strong("Failure Mode: "), card["failure_mode"]], className="mb-2 small"),
                        ], width=6),
                    ]),
                ], style={"backgroundColor": DARK_BG}),
            ],
            className="mb-3",
            style={"border": f"1px solid {GRID_COLOR}", "borderTop": f"3px solid {_color_for(card['color'])}"},
            )
        )
    return cards


def _color_for(name: str) -> str:
    return {"success": GREEN, "primary": ACCENT, "warning": ORANGE, "danger": RED}.get(name, ACCENT)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Starting Commodity Stat-Arb Dashboard on http://127.0.0.1:8050")
    app.run(debug=False, host="127.0.0.1", port=8050)
