from datetime import date
import pandas as pd
import yfinance as yf

from data.providers.base import DataProvider


class YFinanceProvider(DataProvider):
    """Fetches continuous front-month futures via yfinance.

    Suitable for cross-market and ratio spreads (e.g. BZ=F, CL=F, GC=F, SI=F).
    Not reliable for individual expired contract months — use DatabentoPovider for those.
    """

    def fetch_ohlcv(
        self,
        ticker: str,
        start: date,
        end: date,
        exchange: str | None = None,
    ) -> pd.DataFrame:
        raw = yf.download(ticker, start=str(start), end=str(end), auto_adjust=True, progress=False)
        if raw.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "open_interest"])

        # yfinance returns MultiIndex columns when downloading a single ticker with auto_adjust
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        raw = raw.rename(columns=str.lower)
        df = raw[["open", "high", "low", "close", "volume"]].copy()
        df["open_interest"] = float("nan")
        df.index = pd.to_datetime(df.index).date
        df.index.name = "date"
        df = df.dropna(subset=["close"])
        return df
