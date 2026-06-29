"""Unit tests for the Almgren-Chriss execution cost model.

Run with:
    uv run python -m pytest tests/test_almgren_chriss.py -v
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.almgren_chriss import AlmgrenChrissModel, eta_sensitivity


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIGMA = 0.30      # $/bbl daily spread vol
ADV = 500_000.0   # bbls (≈ 500 WTI/Brent contracts)


@pytest.fixture
def base_model() -> AlmgrenChrissModel:
    return AlmgrenChrissModel(eta=0.1, gamma=0.05, alpha=1.0, n_periods=1)


# ---------------------------------------------------------------------------
# Sanity: basic output shape
# ---------------------------------------------------------------------------

def test_compute_returns_positive_costs(base_model):
    r = base_model.compute(1_000, SIGMA, ADV)
    assert r.temp_impact_cost >= 0
    assert r.perm_impact_cost >= 0
    assert r.total_shortfall == pytest.approx(r.temp_impact_cost + r.perm_impact_cost)


def test_zero_quantity_returns_zero(base_model):
    r = base_model.compute(0.0, SIGMA, ADV)
    assert r.temp_impact_cost == 0.0
    assert r.perm_impact_cost == 0.0
    assert r.total_shortfall == 0.0


# ---------------------------------------------------------------------------
# Monotonicity: larger trades → higher impact
# ---------------------------------------------------------------------------

def test_larger_trade_higher_temp_impact(base_model):
    small = base_model.compute(1_000, SIGMA, ADV)
    large = base_model.compute(10_000, SIGMA, ADV)
    assert large.temp_impact_cost > small.temp_impact_cost


def test_larger_trade_higher_perm_impact(base_model):
    small = base_model.compute(1_000, SIGMA, ADV)
    large = base_model.compute(10_000, SIGMA, ADV)
    assert large.perm_impact_cost > small.perm_impact_cost


# ---------------------------------------------------------------------------
# Monotonicity: higher vol → proportionally higher costs
# ---------------------------------------------------------------------------

def test_higher_vol_higher_costs(base_model):
    low_vol = base_model.compute(1_000, 0.10, ADV)
    high_vol = base_model.compute(1_000, 0.50, ADV)
    assert high_vol.temp_impact_cost > low_vol.temp_impact_cost
    assert high_vol.perm_impact_cost > low_vol.perm_impact_cost


def test_cost_scales_linearly_with_vol_alpha1(base_model):
    r1 = base_model.compute(1_000, 0.20, ADV)
    r2 = base_model.compute(1_000, 0.40, ADV)
    # For α=1 and linear gamma, costs scale linearly with σ
    assert r2.temp_impact_cost == pytest.approx(r1.temp_impact_cost * 2, rel=1e-6)
    assert r2.perm_impact_cost == pytest.approx(r1.perm_impact_cost * 2, rel=1e-6)


# ---------------------------------------------------------------------------
# Alpha exponent: square-root (α=0.5) vs. linear (α=1.0)
# ---------------------------------------------------------------------------

def test_alpha_half_sublinear_scaling():
    """With α=0.5, doubling trade size should give less than double the per-unit cost."""
    m = AlmgrenChrissModel(eta=0.1, gamma=0.05, alpha=0.5)
    r1 = m.compute(1_000, SIGMA, ADV)
    r2 = m.compute(2_000, SIGMA, ADV)
    # Per-unit temp cost = total / qty; should be higher for larger order but not double
    per_unit_1 = r1.temp_impact_cost / 1_000
    per_unit_2 = r2.temp_impact_cost / 2_000
    assert per_unit_2 > per_unit_1  # larger trade → higher per-unit cost
    assert per_unit_2 < per_unit_1 * 2  # but sub-linear (square-root concavity)


def test_alpha_half_more_expensive_at_low_participation():
    """At participation rates < 1 (p^0.5 > p^1), square-root impact exceeds linear impact.

    This is the concavity of the square-root: for a small order relative to ADV,
    sqrt gives higher per-unit impact than linear with the same η.
    """
    q = 50_000  # participation = 50k / 500k = 10% < 1 → p^0.5 > p^1
    m_linear = AlmgrenChrissModel(eta=0.1, gamma=0.05, alpha=1.0)
    m_sqrt = AlmgrenChrissModel(eta=0.1, gamma=0.05, alpha=0.5)
    r_linear = m_linear.compute(q, SIGMA, ADV)
    r_sqrt = m_sqrt.compute(q, SIGMA, ADV)
    # For p=0.1: p^0.5=0.316 > p^1=0.1, so sqrt is more expensive at this scale
    assert r_sqrt.temp_impact_cost > r_linear.temp_impact_cost


# ---------------------------------------------------------------------------
# Time-of-day adjustment
# ---------------------------------------------------------------------------

def test_mid_session_factor_is_lowest():
    """Mid-session (12:00 ET) should have lower factor than open or close."""
    f_open = AlmgrenChrissModel.time_of_day_factor(9.0)
    f_mid = AlmgrenChrissModel.time_of_day_factor(13.0)
    f_close = AlmgrenChrissModel.time_of_day_factor(17.0)
    assert f_open > f_mid
    assert f_close > f_mid


def test_tod_none_returns_one():
    assert AlmgrenChrissModel.time_of_day_factor(None) == 1.0


def test_tod_elevates_cost_at_open(base_model):
    r_mid = base_model.compute(1_000, SIGMA, ADV, hour=13.0)
    r_open = base_model.compute(1_000, SIGMA, ADV, hour=9.0)
    assert r_open.temp_impact_cost > r_mid.temp_impact_cost


def test_tod_curve_u_shaped():
    """Full trading session curve should be U-shaped (symmetric around mid)."""
    hours, factors = AlmgrenChrissModel.tod_curve(n_points=50)
    mid_idx = len(factors) // 2
    # Both ends higher than middle
    assert factors[0] > factors[mid_idx]
    assert factors[-1] > factors[mid_idx]


# ---------------------------------------------------------------------------
# Calibration from volume
# ---------------------------------------------------------------------------

def test_calibrate_from_volume_produces_positive_eta():
    m = AlmgrenChrissModel.calibrate_from_volume(sigma=0.30, adv_bbls=500_000.0)
    assert m.eta > 0
    assert m.gamma > 0


def test_calibrate_higher_adv_lower_eta():
    m_low = AlmgrenChrissModel.calibrate_from_volume(sigma=0.30, adv_bbls=100_000.0)
    m_high = AlmgrenChrissModel.calibrate_from_volume(sigma=0.30, adv_bbls=1_000_000.0)
    assert m_low.eta > m_high.eta  # lower ADV → higher impact → higher η


def test_calibrate_higher_sigma_higher_eta():
    m_low = AlmgrenChrissModel.calibrate_from_volume(sigma=0.10, adv_bbls=500_000.0)
    m_high = AlmgrenChrissModel.calibrate_from_volume(sigma=0.50, adv_bbls=500_000.0)
    assert m_high.eta > m_low.eta


def test_calibrate_zero_adv_does_not_crash():
    m = AlmgrenChrissModel.calibrate_from_volume(sigma=0.30, adv_bbls=0.0)
    assert m.eta > 0


# ---------------------------------------------------------------------------
# Participation rate
# ---------------------------------------------------------------------------

def test_participation_rate_is_fraction_of_adv(base_model):
    qty = ADV * 0.10  # 10% of ADV
    r = base_model.compute(qty, SIGMA, ADV)
    assert r.participation_rate == pytest.approx(0.10, rel=1e-6)


# ---------------------------------------------------------------------------
# Sensitivity helper
# ---------------------------------------------------------------------------

def test_eta_sensitivity_returns_sorted_costs(base_model):
    rows = eta_sensitivity(base_model, 1_000, SIGMA, ADV, [0.5, 1.0, 2.0])
    costs = [r["total_shortfall"] for r in rows]
    # Costs should increase monotonically with η multiplier
    assert costs[0] < costs[1] < costs[2]


def test_eta_sensitivity_returns_five_rows_default(base_model):
    rows = eta_sensitivity(base_model, 1_000, SIGMA, ADV)
    assert len(rows) == 5


# ---------------------------------------------------------------------------
# as_dict / repr
# ---------------------------------------------------------------------------

def test_as_dict_contains_required_keys(base_model):
    d = base_model.as_dict()
    assert "ac_eta" in d
    assert "ac_gamma" in d
    assert "ac_alpha" in d
    assert "ac_n_periods" in d


def test_repr_contains_eta(base_model):
    assert "η=" in repr(base_model)
