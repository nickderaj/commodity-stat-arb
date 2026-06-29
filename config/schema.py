from pydantic import BaseModel, field_validator


class LegConfig(BaseModel):
    ticker: str           # root ticker, e.g. "CL" for WTI, "BZ=F" for yfinance continuous
    provider: str         # "databento" | "yfinance"
    exchange: str         # "CME" | "ICE" | "COMEX" | "NYMEX" | "CBOT"
    month_offset: int     # 0 = M1 (front), 1 = M2 (second month), etc.
    price_multiplier: float = 1.0  # unit conversion (e.g. 42 for $/gal -> $/bbl)


class SpreadDefinition(BaseModel):
    name: str
    display_name: str
    spread_type: str   # "calendar" | "cross_market" | "crack" | "crush" | "ratio"
    legs: list[LegConfig]
    weights: list[float]  # e.g. [1.0, -1.0]; same length as legs
    economic_tether: str
    expected_half_life_days: int
    roll_offset_days: int = 5  # how many days before expiry to roll (calendar mode)
    roll_mode: str = "calendar"  # "calendar" | "oi"

    @field_validator("weights")
    @classmethod
    def weights_match_legs(cls, v: list[float], info) -> list[float]:
        legs = info.data.get("legs", [])
        if legs and len(v) != len(legs):
            raise ValueError("weights length must match legs length")
        return v
