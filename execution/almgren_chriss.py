"""Almgren-Chriss execution cost simulator.

IMPORTANT: This is a *stylized/illustrative* implementation on daily bars.
True Almgren-Chriss calibration requires intraday transaction data to measure
impact coefficients η and γ empirically. On daily OHLCV, we use literature-
based heuristics:
  - η calibrated from the square-root-of-volume rule: η ≈ k·σ/√ADV
  - γ ≈ 0.5·η (permanent impact typically smaller than temporary)
  - Time-of-day curve is an assumed U-shape (not estimated from data)

Use this model to stress-test sensitivity to η and to show a principled cost
structure, not to claim precise slippage numbers.

Reference: Almgren & Chriss (2000), "Optimal Execution of Portfolio Transactions."
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ACResult:
    """Cost decomposition from one simulated AC execution."""

    temp_impact_cost: float
    perm_impact_cost: float
    total_shortfall: float
    participation_rate: float
    eta_effective: float
    tod_factor: float

    @property
    def spread_cost_est(self) -> float:
        return 0.0


@dataclass
class ACParams:
    eta: float
    gamma: float
    alpha: float
    n_periods: int
    lot_size: int

    def as_dict(self) -> dict:
        return {
            "ac_eta": self.eta,
            "ac_gamma": self.gamma,
            "ac_alpha": self.alpha,
            "ac_n_periods": self.n_periods,
        }


class AlmgrenChrissModel:
    """Almgren-Chriss execution cost model calibrated for commodity futures.

    Model
    -----
    Temporary impact (cost per bbl for a single child order):
        h(v) = η_eff · σ · (participation_rate)^α
    where:
        participation_rate = quantity_bbls / (adv_bbls · n_periods)
        η_eff = η · time_of_day_factor(hour)

    Total temporary cost: h(v) · quantity_bbls

    Permanent impact (per bbl, amortized over trade):
        g(x) = γ · σ · (quantity_bbls / adv_bbls)
    Total permanent cost: g(x) · quantity_bbls / 2

    Parameters
    ----------
    eta : float
        Dimensionless temporary impact coefficient. Calibrate via
        `calibrate_from_volume()`. Typical range for liquid futures: 0.05–0.5.
    gamma : float
        Dimensionless permanent impact coefficient. Typically 0.3–0.5 × η.
    alpha : float
        Exponent on participation rate. α=1.0 → linear (TWAP optimal);
        α=0.5 → square-root law (empirically observed in equities).
    n_periods : int
        Number of TWAP slices assumed. Higher n_periods → lower temp impact.
        For daily fills with no intraday data, use n_periods=1 (assume
        single fill per day).
    lot_size : int
        Bbls per exchange contract (1 000 for WTI/Brent).
    """

    def __init__(
        self,
        eta: float = 0.1,
        gamma: float = 0.05,
        alpha: float = 1.0,
        n_periods: int = 1,
        lot_size: int = 1_000,
    ) -> None:
        self.eta = eta
        self.gamma = gamma
        self.alpha = alpha
        self.n_periods = n_periods
        self.lot_size = lot_size

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    @classmethod
    def calibrate_from_volume(
        cls,
        sigma: float,
        adv_bbls: float,
        k_eta: float = 0.1,
        alpha: float = 1.0,
        n_periods: int = 1,
        lot_size: int = 1_000,
    ) -> "AlmgrenChrissModel":
        """Calibrate η from daily spread vol and average daily volume.

        Square-root-of-volume heuristic:
            η = k_eta · σ / √ADV
        where σ is in $/bbl and ADV is in bbls.

        The factor k_eta controls the scaling (default 0.1 is conservative for
        liquid commodity futures; equity studies often use 0.2–0.5).

        Parameters
        ----------
        sigma : float
            Daily spread realised volatility in $/bbl.
        adv_bbls : float
            Average daily volume in bbls (e.g. 500 000 for ~500 CL contracts).
        k_eta : float
            Calibration constant (dimensionless). Default 0.1.
        """
        if adv_bbls <= 0:
            adv_bbls = 1.0
        eta = k_eta * sigma / math.sqrt(adv_bbls)
        gamma = 0.5 * eta
        return cls(eta=eta, gamma=gamma, alpha=alpha, n_periods=n_periods, lot_size=lot_size)

    # ------------------------------------------------------------------
    # Time-of-day liquidity adjustment
    # ------------------------------------------------------------------

    @staticmethod
    def time_of_day_factor(hour: Optional[float] = None) -> float:
        """U-shaped intraday liquidity multiplier.

        ASSUMED shape based on literature — not estimated from data (daily bars
        carry no intraday information). At market open and close, liquidity is
        tighter and impact is elevated. Mid-session is the cheapest to execute.

        Session: 09:00–17:00 ET (approximate WTI/Brent overlap window).

        Parameters
        ----------
        hour : float, optional
            Hour of day (24-hour, ET). None → assume mid-session (factor = 1.0).

        Returns
        -------
        float
            Multiplier on η. Range: 1.0 (mid-session) to ~1.8 (open/close).
        """
        if hour is None:
            return 1.0

        # Normalise to [0, 1] across session 09:00–17:00 ET
        h_open, h_close = 9.0, 17.0
        t = (hour - h_open) / (h_close - h_open)
        t = max(0.0, min(1.0, t))

        # U-shaped: factor = base + amplitude * (2t - 1)^2
        # At t=0 or t=1 (open/close): factor = base + amplitude
        # At t=0.5 (mid-session): factor = base
        base = 1.0
        amplitude = 0.8
        factor = base + amplitude * (2.0 * t - 1.0) ** 2
        return factor

    @staticmethod
    def tod_curve(n_points: int = 100) -> tuple[list[float], list[float]]:
        """Return (hours, factors) for plotting the full U-shaped curve."""
        hours = [9.0 + i * 8.0 / n_points for i in range(n_points + 1)]
        factors = [AlmgrenChrissModel.time_of_day_factor(h) for h in hours]
        return hours, factors

    # ------------------------------------------------------------------
    # Main cost computation
    # ------------------------------------------------------------------

    def compute(
        self,
        quantity_bbls: float,
        sigma_per_bbl: float,
        adv_bbls: float,
        hour: Optional[float] = None,
    ) -> ACResult:
        """Compute Almgren-Chriss execution costs for one trade.

        Parameters
        ----------
        quantity_bbls : float
            Absolute trade size in bbls (unsigned).
        sigma_per_bbl : float
            Daily spread realised volatility in $/bbl (use rolling 20d ATR).
        adv_bbls : float
            Average daily volume in bbls for the relevant contract(s).
        hour : float, optional
            Assumed execution hour (24-hr ET). None → mid-session (factor = 1.0).

        Returns
        -------
        ACResult
            Breakdown of temporary impact, permanent impact, and total IS.
        """
        quantity_bbls = abs(quantity_bbls)
        if quantity_bbls < 1e-8:
            return ACResult(
                temp_impact_cost=0.0,
                perm_impact_cost=0.0,
                total_shortfall=0.0,
                participation_rate=0.0,
                eta_effective=self.eta,
                tod_factor=1.0,
            )

        if adv_bbls <= 0:
            adv_bbls = 1.0

        tod = self.time_of_day_factor(hour)
        eta_eff = self.eta * tod

        # Participation rate: fraction of ADV executed per period
        participation = quantity_bbls / (adv_bbls * max(self.n_periods, 1))

        # Temporary impact (cost per bbl = η_eff · σ · p^α)
        temp_per_bbl = eta_eff * sigma_per_bbl * (participation ** self.alpha)
        temp_cost = temp_per_bbl * quantity_bbls

        # Permanent impact (Almgren g(x) = γ · x; amortised over position)
        # Total perm cost = γ · σ · (Q/ADV) · Q / 2
        perm_per_bbl = self.gamma * sigma_per_bbl * (quantity_bbls / adv_bbls)
        perm_cost = perm_per_bbl * quantity_bbls / 2.0

        total = temp_cost + perm_cost

        return ACResult(
            temp_impact_cost=temp_cost,
            perm_impact_cost=perm_cost,
            total_shortfall=total,
            participation_rate=participation,
            eta_effective=eta_eff,
            tod_factor=tod,
        )

    # ------------------------------------------------------------------
    # Serialisation (for params hash and DB storage)
    # ------------------------------------------------------------------

    def as_dict(self) -> dict:
        return {
            "ac_eta": self.eta,
            "ac_gamma": self.gamma,
            "ac_alpha": self.alpha,
            "ac_n_periods": self.n_periods,
        }

    def __repr__(self) -> str:
        return (
            f"AlmgrenChrissModel(η={self.eta:.4f}, γ={self.gamma:.4f}, "
            f"α={self.alpha}, n_periods={self.n_periods})"
        )


# ------------------------------------------------------------------
# Sensitivity helpers
# ------------------------------------------------------------------

def eta_sensitivity(
    model_base: AlmgrenChrissModel,
    quantity_bbls: float,
    sigma_per_bbl: float,
    adv_bbls: float,
    eta_multipliers: list[float] | None = None,
) -> list[dict]:
    """Return AC cost breakdown for a range of η multipliers.

    Used to stress-test sensitivity to the impact coefficient calibration.

    Parameters
    ----------
    model_base : AlmgrenChrissModel
        Base model; η is scaled by each multiplier.
    eta_multipliers : list of float, optional
        Scale factors to apply to η. Default: [0.25, 0.5, 1.0, 2.0, 4.0].
    """
    if eta_multipliers is None:
        eta_multipliers = [0.25, 0.5, 1.0, 2.0, 4.0]

    rows = []
    for mult in eta_multipliers:
        m = AlmgrenChrissModel(
            eta=model_base.eta * mult,
            gamma=model_base.gamma * mult,
            alpha=model_base.alpha,
            n_periods=model_base.n_periods,
            lot_size=model_base.lot_size,
        )
        r = m.compute(quantity_bbls, sigma_per_bbl, adv_bbls)
        rows.append(
            {
                "eta_mult": mult,
                "eta": m.eta,
                "temp_cost": r.temp_impact_cost,
                "perm_cost": r.perm_impact_cost,
                "total_shortfall": r.total_shortfall,
                "shortfall_bps": r.total_shortfall / (sigma_per_bbl * quantity_bbls) * 10_000
                if sigma_per_bbl * quantity_bbls > 1e-8
                else float("nan"),
            }
        )
    return rows
