"""Pair screening pipeline for the commodity stat-arb universe.

For each candidate pair, runs:
  1. Correlation pre-filter (rolling 63d return correlation)
  2. Cointegration - Engle-Granger + Johansen for 2-leg pairs
  3. Spread stationarity - ADF + KPSS on the beta-weighted (or fixed-weight) spread
  4. Half-life - AR(1) regression; keep 3-30 day band
  5. Stability - rolling ADF over 252-day windows
  6. Composite score = coint_confidence x hl_suitability x stability

Emits research/screening_report.md and prints a summary table.

CLI usage:
    uv run python research/pair_screener.py [--start 2015-01-01] [--min-score 0.35]
"""

from __future__ import annotations

import argparse
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

from research.stats import (
    composite_score,
    compute_half_life,
    rolling_correlation,
    rolling_stability,
    run_adf,
    run_engle_granger,
    run_johansen,
    run_kpss,
)

OUTPUT_DIR = Path(__file__).parent / "outputs"
REPORT_PATH = Path(__file__).parent / "screening_report.md"


@dataclass
class CandidatePair:
    name: str
    display_name: str
    tickers: list[str]
    weights: list[float]
    spread_type: str
    economic_tether: str
    expected_half_life_days: int
    # For n-leg pairs with mixed units (e.g. crack spread), apply per-leg multiplier
    # before constructing the spread. Default 1.0 for all legs.
    price_multipliers: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.price_multipliers:
            self.price_multipliers = [1.0] * len(self.tickers)

    @property
    def is_two_leg(self) -> bool:
        return len(self.tickers) == 2


# Full candidate universe - economic rationale in docs/notes.md
CANDIDATES: list[CandidatePair] = [
    CandidatePair(
        name="brent_wti",
        display_name="Brent-WTI Cross-Market",
        tickers=["BZ=F", "CL=F"],
        weights=[1.0, -1.0],
        spread_type="cross_market",
        economic_tether="Close substitutes (light sweet crude). Location/quality differential bounded by trade-flow economics.",
        expected_half_life_days=15,
    ),
    CandidatePair(
        name="gold_silver",
        display_name="Gold-Silver Ratio",
        tickers=["GC=F", "SI=F"],
        weights=[1.0, -1.0],
        spread_type="ratio",
        economic_tether="Both monetary/precious metals. Classic gold-silver ratio (historically ~60-80:1) reverts to monetary substitution equilibrium.",
        expected_half_life_days=20,
    ),
    CandidatePair(
        name="crack_321",
        display_name="3-2-1 Crack Spread",
        tickers=["CL=F", "RB=F", "HO=F"],
        weights=[-3.0, 2.0, 1.0],
        price_multipliers=[1.0, 42.0, 42.0],  # convert $/gal to $/bbl
        spread_type="crack",
        economic_tether="Refining margin: crude input vs gasoline + heating oil output. Physical refinery economics impose a floor/ceiling.",
        expected_half_life_days=15,
    ),
    CandidatePair(
        name="crush_spread",
        display_name="Soybean Crush Spread",
        tickers=["ZS=F", "ZM=F", "ZL=F"],
        weights=[-1.0, 1.0, 1.0],
        # Convert each to $/bushel of soybeans processed:
        # ZM: $/ton -> $/bushel = ZM * 0.02375 (1 bushel -> 47.5 lbs = 0.02375 short tons of meal)
        # ZL: $/lb  -> $/bushel = ZL * 10.7    (1 bushel -> 10.7 lbs of oil)
        # ZS: already $/bushel
        price_multipliers=[1.0, 0.02375, 10.7],
        spread_type="crush",
        economic_tether="Processing margin: soybean input vs meal + oil output. Crushing economics and soy complex substitution create mean reversion.",
        expected_half_life_days=15,
    ),
    CandidatePair(
        name="gold_platinum",
        display_name="Gold-Platinum",
        tickers=["GC=F", "PL=F"],
        weights=[1.0, -1.0],
        spread_type="ratio",
        economic_tether="Both precious metals, some substitution in jewelry/investment. Weaker tether than gold-silver (platinum is more industrial).",
        expected_half_life_days=30,
    ),
    CandidatePair(
        name="platinum_palladium",
        display_name="Platinum-Palladium (PGMs)",
        tickers=["PL=F", "PA=F"],
        weights=[1.0, -1.0],
        spread_type="ratio",
        economic_tether="Both autocatalyst PGMs. Substitution possible in catalytic converters (palladium for gasoline, platinum for diesel). Supply from same mines (SA, Russia).",
        expected_half_life_days=20,
    ),
    CandidatePair(
        name="corn_wheat",
        display_name="Corn-Wheat Feed Grains",
        tickers=["ZC=F", "ZW=F"],
        weights=[1.0, -1.0],
        spread_type="ratio",
        economic_tether="Substitutable feed grains in animal feed rations. Feed buyers switch between them at price crossover, creating mean reversion.",
        expected_half_life_days=20,
    ),
    CandidatePair(
        name="copper_silver",
        display_name="Copper-Silver (control)",
        tickers=["HG=F", "SI=F"],
        weights=[1.0, -1.0],
        spread_type="ratio",
        economic_tether="CONTROL - expected to fail. Copper is pure industrial (construction, EVs), silver is half-monetary. No strong economic tether.",
        expected_half_life_days=999,
    ),
]


def fetch_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Download closing prices for a list of yfinance tickers. Returns wide DataFrame."""
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw.iloc[:, raw.columns.get_level_values(0) == "Close"]
    else:
        closes = raw[["Close"]] if "Close" in raw.columns else raw
        closes.columns = tickers[:1]

    closes.columns = [str(c) for c in closes.columns]
    closes.index = pd.to_datetime(closes.index)
    return closes.dropna(how="all")


def build_spread(
    prices: pd.DataFrame,
    candidate: CandidatePair,
    ols_beta: float | None = None,
) -> pd.Series:
    """Construct spread from prices using candidate weights and multipliers.

    For 2-leg pairs: if ols_beta is provided, uses spread = leg1 - ols_beta * leg2
    (ignoring the candidate weights, which are just [+1, -1] placeholders).
    For n-leg pairs: spread = sum(price_i * multiplier_i * weight_i) / |sum(weights)|.
    """
    cols = candidate.tickers
    p = prices[cols].dropna()

    if candidate.is_two_leg and ols_beta is not None:
        spread = p[cols[0]] - ols_beta * p[cols[1]]
    else:
        # Fixed-weight spread (n-leg or 2-leg without fitted beta)
        parts = []
        for ticker, w, m in zip(cols, candidate.weights, candidate.price_multipliers):
            parts.append(p[ticker] * m * w)
        spread = sum(parts)
        # Normalize by sum of absolute weights so different spreads are comparable
        norm = sum(abs(w) for w in candidate.weights)
        if norm > 0:
            spread = spread / norm

    return spread.dropna().rename(candidate.name)


@dataclass
class ScreeningResult:
    name: str
    display_name: str
    spread_type: str
    mean_corr: float
    eg_p: float | None       # None for n-leg pairs
    ols_beta: float | None
    jo_r0_reject: bool | None
    adf_p: float
    kpss_p: float
    mean_hl: float
    hl_p25: float
    hl_p75: float
    stability: float
    score: float
    n_obs: int
    verdict: str


def screen_pair(candidate: CandidatePair, prices: pd.DataFrame) -> ScreeningResult | None:
    cols = candidate.tickers
    missing = [t for t in cols if t not in prices.columns]
    if missing:
        print(f"  SKIP {candidate.name}: missing tickers {missing}")
        return None

    p = prices[cols].dropna()
    if len(p) < 252:
        print(f"  SKIP {candidate.name}: only {len(p)} obs after dropping NaN")
        return None

    s_list = [p[t] for t in cols]

    # 1. Rolling return correlation (first two legs)
    corr_series = rolling_correlation(s_list[0], s_list[1])
    mean_corr = float(corr_series.dropna().mean())

    # 2. Cointegration (EG + Johansen for 2-leg; skip for n-leg)
    eg_p: float | None = None
    ols_beta: float | None = None
    jo_r0_reject: bool | None = None

    if candidate.is_two_leg:
        eg = run_engle_granger(s_list[0], s_list[1])
        jo = run_johansen(s_list[0], s_list[1])
        eg_p = eg["eg_p"]
        ols_beta = eg["ols_beta"]
        jo_r0_reject = jo["jo_r0_reject"]

    # 3. Build spread and run stationarity tests
    spread = build_spread(p, candidate, ols_beta=ols_beta)

    adf = run_adf(spread)
    kpss_res = run_kpss(spread)

    # 4. Half-life
    from research.stats import rolling_half_life
    rl_hl = rolling_half_life(spread, window=min(252, len(spread) // 3), step=21)
    hl_vals = rl_hl["half_life"].dropna()
    mean_hl = float(hl_vals.mean()) if len(hl_vals) > 0 else np.nan
    hl_p25 = float(hl_vals.quantile(0.25)) if len(hl_vals) > 0 else np.nan
    hl_p75 = float(hl_vals.quantile(0.75)) if len(hl_vals) > 0 else np.nan

    # 5. Stability
    stab = rolling_stability(spread, window=min(252, len(spread) // 3), step=21)

    # 6. Composite score - use eg_p if available, else adf_p as proxy
    coint_p_for_score = eg_p if eg_p is not None else adf["adf_p"]
    score = composite_score(coint_p_for_score, mean_hl, stab)

    verdict = "PASS" if score >= 0.25 else "weak" if score >= 0.10 else "FAIL"

    print(
        f"  {candidate.name:<22} corr={mean_corr:+.2f}  "
        f"adf_p={adf['adf_p']:.3f}  "
        f"hl={mean_hl:.1f}d  stab={stab:.0%}  score={score:.3f}  [{verdict}]"
    )

    return ScreeningResult(
        name=candidate.name,
        display_name=candidate.display_name,
        spread_type=candidate.spread_type,
        mean_corr=mean_corr,
        eg_p=eg_p,
        ols_beta=ols_beta,
        jo_r0_reject=jo_r0_reject,
        adf_p=adf["adf_p"],
        kpss_p=kpss_res["kpss_p"],
        mean_hl=mean_hl,
        hl_p25=hl_p25,
        hl_p75=hl_p75,
        stability=stab,
        score=score,
        n_obs=len(spread),
        verdict=verdict,
    )


def _fmt(v: float | None, fmt: str = ".3f", na: str = "N/A") -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return na
    return format(v, fmt)


def write_report(results: list[ScreeningResult], start: str, end: str, min_score: float) -> None:
    results_sorted = sorted(results, key=lambda r: r.score, reverse=True)

    lines = [
        "# Pair Screening Report",
        "",
        f"Period: {start} to {end}  |  Min score for PASS: {min_score}",
        "",
        "Composite score = (1 - coint_p) x HL_suitability x stability",
        "",
        "- coint_p: Engle-Granger p-value for 2-leg pairs; ADF p-value for n-leg",
        "- HL suitability: 1.0 in 3-30d band, decays outside",
        "- stability: fraction of rolling 252-day windows where ADF rejects unit root",
        "",
        "## Results",
        "",
        "| Pair | Type | Corr | EG p | beta | ADF p | KPSS p | Mean HL | HL p25 | HL p75 | Stab | Score | Verdict |",
        "|------|------|------|------|------|-------|--------|---------|--------|--------|------|-------|---------|",
    ]

    for r in results_sorted:
        eg_p_str = _fmt(r.eg_p) if r.eg_p is not None else "N/A"
        beta_str = _fmt(r.ols_beta, ".2f") if r.ols_beta is not None else "N/A"
        jo_str = str(r.jo_r0_reject) if r.jo_r0_reject is not None else "N/A"
        lines.append(
            f"| {r.display_name} | {r.spread_type} | {_fmt(r.mean_corr, '+.2f')} "
            f"| {eg_p_str} | {beta_str} "
            f"| {_fmt(r.adf_p)} | {_fmt(r.kpss_p)} "
            f"| {_fmt(r.mean_hl, '.1f')}d | {_fmt(r.hl_p25, '.1f')}d | {_fmt(r.hl_p75, '.1f')}d "
            f"| {_fmt(r.stability, '.0%')} | {_fmt(r.score, '.3f')} | **{r.verdict}** |"
        )

    passing = [r for r in results_sorted if r.verdict == "PASS"]
    lines += [
        "",
        "## Promoted Pairs",
        "",
        f"Pairs with score >= {min_score} promoted to SpreadDefinition configs:",
        "",
    ]
    for r in passing:
        lines.append(f"- `{r.name}` ({r.display_name}) - score {r.score:.3f}, mean HL {r.mean_hl:.1f}d")

    lines += [
        "",
        "## Economic Notes",
        "",
        "- 2-leg pairs: EG test fits OLS hedge ratio. Spread = leg1 - beta * leg2.",
        "- Crack spread: 3-2-1 ratio (2x RBOB + 1x HO - 3x CL), gasoline/heating oil converted from $/gal to $/bbl (*42).",
        "- Crush spread: per-bushel gross processing margin. ZM converted by 0.02375 short tons/bushel, ZL by 10.7 lbs/bushel.",
        "- Copper-silver is the control pair - no strong economic tether expected.",
    ]

    REPORT_PATH.write_text("\n".join(lines))
    print(f"\nReport written to {REPORT_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Commodity pair screening pipeline")
    parser.add_argument("--start", default="2015-01-01", help="Start date for price history")
    parser.add_argument("--end", default="2025-01-01", help="End date for price history")
    parser.add_argument("--min-score", type=float, default=0.25, help="Min composite score for PASS")
    args = parser.parse_args()

    all_tickers = list({t for c in CANDIDATES for t in c.tickers})
    print(f"Downloading {len(all_tickers)} tickers from {args.start} to {args.end} ...")
    prices = fetch_prices(all_tickers, start=args.start, end=args.end)
    print(f"Got {len(prices)} trading days\n")

    results = []
    for candidate in CANDIDATES:
        result = screen_pair(candidate, prices)
        if result is not None:
            results.append(result)

    results_sorted = sorted(results, key=lambda r: r.score, reverse=True)
    print("\n=== FINAL RANKING ===")
    print(f"{'Pair':<28} {'Score':>6}  Verdict")
    print("-" * 45)
    for r in results_sorted:
        print(f"{r.display_name:<28} {r.score:>6.3f}  {r.verdict}")

    write_report(results, args.start, args.end, args.min_score)


if __name__ == "__main__":
    main()
