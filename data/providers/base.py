"""Abstract base class for OHLCV data providers."""

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class DataProvider(ABC):
    """Abstract interface for OHLCV data sources."""

    @abstractmethod
    def fetch_ohlcv(
        self,
        ticker: str,
        start: date,
        end: date,
        exchange: str | None = None,
    ) -> pd.DataFrame:
        """Return a DataFrame with columns: date, open, high, low, close, volume, open_interest.

        date is the index (dtype: datetime.date).
        All price columns are float; volume and open_interest are int (may be NaN).
        """
        ...
