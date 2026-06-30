"""Pydantic config models for spread definitions.

SpreadDefinition is the central config object. All downstream modules (engine, screener,
series builder) read tickers and weights from a SpreadDefinition - never from hardcoded strings.
"""

from pydantic import BaseModel, field_validator


class LegConfig(BaseModel):
    """Configuration for one leg of a spread.

    Parameters
    ----------
    ticker : str
        Root ticker, e.g. "CL" for WTI or "BZ=F" for yfinance continuous.
    provider : str
        Data source: "databento" (contract-level) or "yfinance" (continuous front-month).
    exchange : str
        Exchange code: "CME", "ICE", "COMEX", "NYMEX", or "CBOT".
    month_offset : int
        Contract month relative to front: 0=M1 (front), 1=M2 (second month), etc.
    price_multiplier : float
        Unit conversion factor applied before spread construction (e.g. 42 to convert $/gal to $/bbl).
    """

    ticker: str
    provider: str
    exchange: str
    month_offset: int
    price_multiplier: float = 1.0


class SpreadDefinition(BaseModel):
    """Full configuration for a tradeable spread.

    Parameters
    ----------
    name : str
        Machine-readable identifier, e.g. "wti_calendar".
    display_name : str
        Human-readable label for UI and reports.
    spread_type : str
        Structural category: "calendar", "cross_market", "crack", "crush", or "ratio".
    legs : list[LegConfig]
        Ordered list of legs. Spread value = sum(weight_i * price_i * multiplier_i).
    weights : list[float]
        Signed weights per leg, same length as legs. E.g. [1.0, -1.0] for long leg1 / short leg2.
    economic_tether : str
        Plain-English description of the arbitrage relationship keeping this spread bounded.
    expected_half_life_days : int
        Prior estimate of mean-reversion half-life in days (used for lookback heuristics).
    roll_offset_days : int
        Days before expiry to begin rolling in calendar mode. Default 5.
    roll_mode : str
        Roll timing rule: "calendar" (N days before expiry) or "oi" (OI crossover). Default "calendar".
    """

    name: str
    display_name: str
    spread_type: str
    legs: list[LegConfig]
    weights: list[float]
    economic_tether: str
    expected_half_life_days: int
    roll_offset_days: int = 5
    roll_mode: str = "calendar"

    @field_validator("weights")
    @classmethod
    def weights_match_legs(cls, v: list[float], info) -> list[float]:
        legs = info.data.get("legs", [])
        if legs and len(v) != len(legs):
            raise ValueError("weights length must match legs length")
        return v
