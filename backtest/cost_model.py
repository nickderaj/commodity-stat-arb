"""Transaction cost model for the backtest engine.

Three configurable cost components applied per round-trip trade:
- Commission: flat fee per contract per side
- Bid-ask spread cost: HL-range proxy or fixed bps of spread price
- Slippage: fixed bps execution shortfall (fallback before AC model in Phase 6)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostBreakdown:
    commission: float
    spread_cost: float
    slippage: float

    @property
    def total(self) -> float:
        return self.commission + self.spread_cost + self.slippage


class CostModel:
    """Configurable round-trip transaction cost model.

    The spread series is quoted in $/bbl; position size (``quantity``) is in
    bbls. Commissions are charged per exchange contract (1 contract = ``lot_size``
    bbls), so commission = commission_per_contract x ceil(quantity / lot_size) x 2.
    Bid-ask and slippage scale linearly with quantity in bbls.

    Parameters
    ----------
    commission_per_contract : float
        Flat fee per exchange contract per side ($1.50–$5.00 typical).
        Charged on entry AND exit (round-trip = x2).
    spread_bps : float
        Bid-ask half-spread in basis points of the spread price ($/bbl).
        If ``hl_range_pct`` is passed to ``compute()``, that overrides this.
    slippage_bps : float
        Fixed-bps execution slippage per side (market-order shortfall proxy).
        Replaced by the Almgren-Chriss model in Phase 6.
    lot_size : int
        Bbls per exchange contract (1 000 for WTI/Brent NYMEX/ICE lots).
        Used to convert position size in bbls → number of lots for commission.
    """

    def __init__(
        self,
        commission_per_contract: float = 2.0,
        spread_bps: float = 5.0,
        slippage_bps: float = 2.0,
        lot_size: int = 1_000,
    ) -> None:
        self.commission_per_contract = commission_per_contract
        self.spread_bps = spread_bps
        self.slippage_bps = slippage_bps
        self.lot_size = lot_size

    def compute(
        self,
        entry_price: float,
        exit_price: float,
        quantity: int = 1,
        hl_range_pct: float | None = None,
    ) -> CostBreakdown:
        """Compute round-trip transaction costs for one completed trade.

        Parameters
        ----------
        entry_price, exit_price : float
            Spread values at entry and exit ($/bbl, for bps scaling).
        quantity : int
            Position size in bbls.
        hl_range_pct : float, optional
            (High - Low) / Close from contract_metrics. Overrides spread_bps
            when provided and positive.
        """
        import math
        avg_price = (abs(entry_price) + abs(exit_price)) / 2
        if avg_price < 1e-8:
            avg_price = 1.0

        # Lots = ceiling(quantity / lot_size); commission charged per lot per side
        n_lots = max(1, math.ceil(quantity / self.lot_size))
        commission = self.commission_per_contract * n_lots * 2

        # Bid-ask: use HL proxy if available, else fixed bps; scale by bbls
        if hl_range_pct is not None and hl_range_pct > 0:
            half_spread_cost = hl_range_pct / 2 * avg_price
        else:
            half_spread_cost = self.spread_bps / 10_000 * avg_price
        spread_cost = half_spread_cost * 2 * quantity

        # Slippage: fixed bps, both sides, scale by bbls
        slippage = self.slippage_bps / 10_000 * avg_price * 2 * quantity

        return CostBreakdown(
            commission=commission,
            spread_cost=spread_cost,
            slippage=slippage,
        )

    def as_dict(self) -> dict:
        return {
            "commission_per_contract": self.commission_per_contract,
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
            "lot_size": self.lot_size,
        }
