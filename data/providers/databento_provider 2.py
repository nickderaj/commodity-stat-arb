import os
from datetime import date
import pandas as pd
from dotenv import load_dotenv

from data.providers.base import DataProvider

load_dotenv()

# Databento dataset identifiers
_CME_DATASET = "GLBX.MDP3"
_ICE_DATASET = "IFEU.IMPACT"

_EXCHANGE_TO_DATASET = {
    "CME": _CME_DATASET,
    "ICE": _ICE_DATASET,
}

# Futures month codes: January=F, February=G, ..., December=Z
_MONTH_CODES = "FGHJKMNQUVXZ"


def _contract_symbol(product: str, year: int, month: int) -> str:
    """Return the Databento symbol for a futures contract, e.g. CLF4 for WTI Jan 2024."""
    code = _MONTH_CODES[month - 1]
    year_suffix = str(year)[-1]  # last digit of year
    return f"{product}{code}{year_suffix}"


class DatabentoPovider(DataProvider):
    """Fetches individual contract-month OHLCV from Databento.

    Required for calendar spreads where individual expired contracts
    (e.g. CLF24, CLG24, BZF24) are needed. yfinance cannot serve these.
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("DATABENTO_API_KEY")
        if not self._api_key:
            raise EnvironmentError(
                "DATABENTO_API_KEY is not set. "
                "Add it to your .env file. See .env.example."
            )

    def fetch_ohlcv(
        self,
        ticker: str,
        start: date,
        end: date,
        exchange: str | None = "CME",
    ) -> pd.DataFrame:
        """Fetch daily OHLCV for a specific futures contract symbol.

        ticker should be the full contract symbol, e.g. "CLF4" or "BZG5".
        For bulk fetching of all months in a date range, use fetch_all_contracts().
        """
        import databento as db

        dataset = _EXCHANGE_TO_DATASET.get(exchange or "CME", _CME_DATASET)
        client = db.Historical(key=self._api_key)

        data = client.timeseries.get_range(
            dataset=dataset,
            symbols=[ticker],
            schema="ohlcv-1d",
            start=str(start),
            end=str(end),
        )
        df = data.to_df()
        if df.empty:
            return pd.DataFrame(
                columns=["date", "open", "high", "low", "close", "volume", "open_interest"]
            )

        df = df.rename(columns={
            "ts_event": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        })
        # Databento prices are in fixed-point (multiplied by 1e9 for equities; check units for futures)
        # For futures OHLCV, prices are in price currency already
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.set_index("date")
        if "open_interest" not in df.columns:
            df["open_interest"] = float("nan")

        return df[["open", "high", "low", "close", "volume", "open_interest"]]

    def fetch_all_contracts(
        self,
        product: str,
        exchange: str,
        start: date,
        end: date,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for all contract months of a product within a date range.

        Returns a dict keyed by contract symbol, e.g. {"CLF4": df, "CLG4": df, ...}.
        """
        import databento as db

        dataset = _EXCHANGE_TO_DATASET.get(exchange, _CME_DATASET)
        client = db.Historical(key=self._api_key)

        # Use parent symbol to get all contracts
        data = client.timeseries.get_range(
            dataset=dataset,
            symbols=[f"{product}.FUT"],
            stype_in="parent",
            schema="ohlcv-1d",
            start=str(start),
            end=str(end),
        )
        df = data.to_df()
        if df.empty:
            return {}

        df["date"] = pd.to_datetime(df["ts_event"]).dt.date
        if "open_interest" not in df.columns:
            df["open_interest"] = float("nan")

        result: dict[str, pd.DataFrame] = {}
        for symbol, group in df.groupby("symbol"):
            g = group.set_index("date")[["open", "high", "low", "close", "volume", "open_interest"]]
            result[str(symbol)] = g

        return result
