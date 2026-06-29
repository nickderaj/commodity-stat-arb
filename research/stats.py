"""Shared statistical tests for spread analysis.

Covers: ADF, KPSS, Engle-Granger cointegration, Johansen, AR(1) half-life,
Zivot-Andrews structural break, rolling ADF stability, rolling correlation.

No DB dependencies - works in notebooks, screener scripts, and tests alike.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller, coint, kpss, zivot_andrews
from statsmodels.tsa.vector_ar.vecm import coint_johansen


def run_adf(s: pd.Series) -> dict:
    """ADF test. Null: has unit root. Reject (p < 0.05) is evidence of stationarity."""
    res = adfuller(s.dropna().values, autolag="AIC")
    return {
        "adf_stat": res[0],
        "adf_p": res[1],
        "adf_lags": res[2],
        "adf_cv_1pct": res[4]["1%"],
        "adf_cv_5pct": res[4]["5%"],
        "adf_cv_10pct": res[4]["10%"],
    }


def run_kpss(s: pd.Series) -> dict:
    """KPSS test. Null: is stationary. Reject (p < 0.05) is evidence of non-stationarity."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = kpss(s.dropna().values, regression="c", nlags="auto")
    return {
        "kpss_stat": res[0],
        "kpss_p": res[1],
        "kpss_cv_5pct": res[3]["5%"],
    }


def run_engle_granger(s1: pd.Series, s2: pd.Series) -> dict:
    """Engle-Granger cointegration test + OLS hedge ratio for a 2-leg pair.

    The OLS beta is the hedge ratio: spread = s1 - beta * s2.
    """
    idx = s1.index.intersection(s2.index)
    a = s1.loc[idx].dropna()
    b = s2.loc[idx].dropna()
    idx2 = a.index.intersection(b.index)
    a, b = a.loc[idx2], b.loc[idx2]
    eg_stat, eg_p, eg_cvs = coint(a.values, b.values)
    beta = np.cov(a.values, b.values)[0, 1] / np.var(b.values)
    return {
        "eg_stat": eg_stat,
        "eg_p": eg_p,
        "eg_cv_5pct": eg_cvs[1],
        "ols_beta": float(beta),
    }


def run_johansen(s1: pd.Series, s2: pd.Series) -> dict:
    """Johansen trace test for a 2-leg pair. Returns trace stats and normalized hedge ratio."""
    idx = s1.index.intersection(s2.index)
    a = s1.loc[idx].dropna()
    b = s2.loc[idx].dropna()
    idx2 = a.index.intersection(b.index)
    a, b = a.loc[idx2], b.loc[idx2]
    mat = np.column_stack([a.values, b.values])
    jo = coint_johansen(mat, det_order=0, k_ar_diff=1)
    ev = jo.evec[:, 0]
    hedge_ratio = float(-ev[1] / ev[0]) if ev[0] != 0 else np.nan
    return {
        "jo_trace_r0": jo.lr1[0],
        "jo_trace_r0_cv95": jo.cvt[0, 1],
        "jo_r0_reject": bool(jo.lr1[0] > jo.cvt[0, 1]),
        "jo_hedge_ratio": hedge_ratio,
    }


def compute_half_life(s: pd.Series) -> float:
    """Single-pass AR(1) half-life of mean reversion. Returns NaN if b >= 0."""
    arr = s.dropna().values
    if len(arr) < 30:
        return np.nan
    dS = np.diff(arr)
    S_lag = arr[:-1]
    mask = np.isfinite(dS) & np.isfinite(S_lag)
    if mask.sum() < 20:
        return np.nan
    coeffs = np.polyfit(S_lag[mask], dS[mask], 1)
    b = coeffs[0]
    return float(-np.log(2) / b) if b < 0 else np.nan


def rolling_half_life(s: pd.Series, window: int = 252, step: int = 21) -> pd.DataFrame:
    """Rolling AR(1) half-life. Returns DataFrame[b, half_life] indexed by date."""
    records = []
    arr = s.values
    dS = np.diff(arr)
    S_lag = arr[:-1]
    idx = s.index[1:]
    for i in range(window, len(dS) + 1, step):
        sl_dS = dS[i - window : i]
        sl_lag = S_lag[i - window : i]
        mask = np.isfinite(sl_dS) & np.isfinite(sl_lag)
        if mask.sum() < window // 2:
            continue
        coeffs = np.polyfit(sl_lag[mask], sl_dS[mask], 1)
        b = coeffs[0]
        hl = -np.log(2) / b if b < 0 else np.nan
        records.append({"date": idx[i - 1], "b": b, "half_life": hl})
    return pd.DataFrame(records).set_index("date")


def run_zivot_andrews(s: pd.Series) -> dict:
    """Zivot-Andrews test: finds a single endogenous structural break."""
    arr = s.dropna()
    res = zivot_andrews(arr.values, maxlag=12, regression="ct", autolag="AIC")
    stat, p, cvs, _lag, bp_idx = res
    break_date = arr.index[bp_idx] if bp_idx < len(arr) else None
    return {
        "za_stat": float(stat),
        "za_p": float(p),
        "za_cv_5pct": float(cvs["5%"]),
        "break_date": break_date,
    }


def rolling_adf_stat(s: pd.Series, window: int = 252, step: int = 21) -> pd.DataFrame:
    """Rolling ADF statistic for stability assessment. Returns DataFrame[adf_stat, cv_5pct]."""
    records = []
    arr = s.dropna()
    vals = arr.values
    idx = arr.index
    for i in range(window, len(vals) + 1, step):
        sl = vals[i - window : i]
        if not np.all(np.isfinite(sl)):
            continue
        res = adfuller(sl, autolag="AIC")
        records.append({"date": idx[i - 1], "adf_stat": res[0], "cv_5pct": res[4]["5%"]})
    return pd.DataFrame(records).set_index("date")


def rolling_stability(s: pd.Series, window: int = 252, step: int = 21) -> float:
    """Fraction of rolling ADF windows that reject unit root (stat < cv_5pct)."""
    df = rolling_adf_stat(s, window=window, step=step)
    if df.empty:
        return np.nan
    passing = (df["adf_stat"] < df["cv_5pct"]).mean()
    return float(passing)


def rolling_correlation(s1: pd.Series, s2: pd.Series, window: int = 63) -> pd.Series:
    """Rolling return correlation between two price series."""
    idx = s1.index.intersection(s2.index)
    r1 = s1.loc[idx].pct_change().dropna()
    r2 = s2.loc[idx].pct_change().dropna()
    idx2 = r1.index.intersection(r2.index)
    return r1.loc[idx2].rolling(window).corr(r2.loc[idx2])


def composite_score(
    coint_p: float,
    mean_hl: float,
    stability: float,
) -> float:
    """Composite screening score: cointegration confidence x HL suitability x stability.

    Range 0-1. Higher is better.
    - coint_p: cointegration (or ADF) p-value of the spread. Lower = more confident.
    - mean_hl: mean rolling half-life in days. Optimal band is 3-30 days.
    - stability: rolling_stability() output (fraction of windows passing ADF).
    """
    if np.isnan(coint_p) or np.isnan(mean_hl) or np.isnan(stability):
        return 0.0
    coint_confidence = max(0.0, 1.0 - coint_p)
    if 3.0 <= mean_hl <= 30.0:
        hl_score = 1.0
    elif mean_hl < 3.0:
        hl_score = max(0.0, mean_hl / 3.0)
    else:
        hl_score = max(0.0, 1.0 - (mean_hl - 30.0) / 30.0)
    return float(coint_confidence * hl_score * stability)
