import os
import re
import warnings
from datetime import date, timedelta
import pandas as pd
from dotenv import load_dotenv

from data.providers.base import DataProvider

load_dotenv()

_CME_DATASET = "GLBX.MDP3"
_ICE_DATASET = "IFEU.IMPACT"

_EXCHANGE_TO_DATASET = {
    "CME": _CME_DATASET,
    "ICE": _ICE_DATASET,
}

_MONTH_CODES = "FGHJKMNQUVXZ"

# Known dataset availability floors (fallback if API error can't be parsed)
_DATASET_AVAILABLE_FROM: dict[str, date] = {
    _CME_DATASET: date(2018, 1, 2),
    _ICE_DATASET: date(2018, 12, 23),
}


def _clamp_start(start: date, dataset: str) -> date:
    """Ensure start is not before the dataset's known available start."""
    floor = _DATASET_AVAILABLE_FROM.get(dataset)
    if floor and start < floor:
        print(f"    Adjusting start {start} → {floor} (dataset {dataset} availability floor)")
        return floor
    return start


def _parse_available_start_from_error(msg: str) -> date | None:
    """Extract the available start date from a data_start_before_available_start error."""
    match = re.search(r"available start of dataset \S+ \('(\d{4}-\d{2}-\d{2})", msg)
    if match:
        return date.fromisoformat(match.group(1))
    return None


def _parse_available_end_from_error(msg: str) -> date | None:
    """Extract the max allowed end date from a dataset_unavailable_range error."""
    match = re.search(r"end time before (\d{4}-\d{2}-\d{2})", msg)
    if match:
        return date.fromisoformat(match.group(1))
    return None


def _resolve_contract_month(symbol: str, product: str, max_bar_date) -> str | None:
    """Derive YYYY-MM contract month from a symbol and the latest bar date.

    Uses the latest bar date to disambiguate the year digit — e.g. 'CLF8' with
    bars through 2018 → '2018-01', while 'CLF8' with bars through 2026 → '2028-01'.
    The year is the earliest year Y such that Y % 10 == year_digit and Y >= max_bar_date.year.
    This is correct because futures bars only exist up to the contract's expiry month.
    """
    root = product.replace("=F", "")
    suffix = symbol[len(root):]
    if len(suffix) < 2:
        return None
    month_code = suffix[0].upper()
    if month_code not in _MONTH_CODES:
        return None
    year_digit = int(suffix[1])
    month = _MONTH_CODES.index(month_code) + 1

    y = max_bar_date.year
    for candidate in range(y, y + 10):
        if candidate % 10 == year_digit:
            return f"{candidate}-{month:02d}"
    return None


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
        import databento as db

        dataset = _EXCHANGE_TO_DATASET.get(exchange or "CME", _CME_DATASET)
        client = db.Historical(key=self._api_key)
        start = _clamp_start(start, dataset)

        data = client.timeseries.get_range(
            dataset=dataset,
            symbols=[ticker],
            schema="ohlcv-1d",
            start=str(start),
            end=str(end),
        )
        return self._to_df(data)

    def fetch_all_contracts(
        self,
        product: str,
        exchange: str,
        start: date,
        end: date,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV for all contract months of a product within a date range.

        Returns a dict keyed by contract month (YYYY-MM), e.g. {"2024-01": df, ...}.
        Groups by instrument_id so two contracts sharing a symbol (e.g. CLF8 in 2018
        and CLF8 as the 2028 deferred contract) are never mixed into the same row.
        """
        import databento as db
        from databento.common.error import BentoClientError

        dataset = _EXCHANGE_TO_DATASET.get(exchange, _CME_DATASET)
        client = db.Historical(key=self._api_key)
        start = _clamp_start(start, dataset)

        def _do_fetch(s: date, e: date):
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*degraded.*")
                return client.timeseries.get_range(
                    dataset=dataset,
                    symbols=[f"{product}.FUT"],
                    stype_in="parent",
                    schema="ohlcv-1d",
                    start=str(s),
                    end=str(e),
                )

        try:
            data = _do_fetch(start, end)
        except BentoClientError as e:
            err = str(e)
            if "data_start_before_available_start" in err:
                available = _parse_available_start_from_error(err)
                if available:
                    print(f"    Dataset {dataset} available from {available}, retrying...")
                    _DATASET_AVAILABLE_FROM[dataset] = available
                    start = available
                    data = _do_fetch(start, end)
                else:
                    raise
            elif "dataset_unavailable_range" in err:
                available_end = _parse_available_end_from_error(err)
                if available_end:
                    clamped_end = available_end - timedelta(days=1)
                    print(f"    Dataset {dataset} free tier ends {available_end}, retrying with {clamped_end}...")
                    data = _do_fetch(start, clamped_end)
                else:
                    raise
            else:
                raise

        return self._split_by_contract(data, product)

    @staticmethod
    def _normalize_ts_event(df: pd.DataFrame) -> pd.DataFrame:
        """Ensure ts_event is a column (newer databento sets it as the index)."""
        if df.index.name == "ts_event":
            df = df.reset_index()
        return df

    def _to_df(self, data) -> pd.DataFrame:
        df = data.to_df()
        if df.empty:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume", "open_interest"]
            )
        df = self._normalize_ts_event(df)
        df["date"] = pd.to_datetime(df["ts_event"]).dt.date
        df = df.set_index("date")
        if "open_interest" not in df.columns:
            df["open_interest"] = float("nan")
        return df[["open", "high", "low", "close", "volume", "open_interest"]]

    def _split_by_contract(self, data, product: str) -> dict[str, pd.DataFrame]:
        """Split a multi-contract response into per-contract DataFrames.

        Groups by instrument_id (unique per real contract) to prevent two contracts
        with the same textual symbol (e.g. BZZ8 in 2018 vs BZZ8 deferred to 2028)
        from being merged. The contract month (YYYY-MM) is resolved using the
        latest bar date to disambiguate the single-digit year code.

        When multiple instrument_ids resolve to the same contract_month (e.g. the
        outright CLF8 future AND a CLF8-tagged calendar spread product both returned
        under the CL.FUT parent), we keep only the instrument with the highest total
        volume — that is always the outright futures contract.
        """
        df = data.to_df()
        if df.empty:
            return {}
        df = self._normalize_ts_event(df)
        df["date"] = pd.to_datetime(df["ts_event"]).dt.date
        if "open_interest" not in df.columns:
            df["open_interest"] = float("nan")

        group_col = "instrument_id" if "instrument_id" in df.columns else "symbol"

        # Minimum mean-close that distinguishes outright futures from calendar spreads.
        # Crude oil outrights trade well above $5/bbl on average over their lifetime;
        # calendar spread contracts (M1-M2 prices) are typically $0–5.
        _OUTRIGHT_PRICE_FLOOR = 5.0

        result: dict[str, pd.DataFrame] = {}
        result_vol: dict[str, float] = {}
        result_is_outright: dict[str, bool] = {}

        for _, group in df.groupby(group_col):
            symbol = str(group["symbol"].iloc[0])
            g = group.set_index("date")[["open", "high", "low", "close", "volume", "open_interest"]]
            contract_month = _resolve_contract_month(symbol, product, g.index.max())
            if contract_month is None:
                continue
            total_vol = float(g["volume"].sum()) if not g["volume"].isna().all() else 0.0
            mean_close = float(g["close"].abs().mean()) if not g["close"].isna().all() else 0.0
            is_outright = mean_close >= _OUTRIGHT_PRICE_FLOOR

            if contract_month not in result:
                result[contract_month] = g
                result_vol[contract_month] = total_vol
                result_is_outright[contract_month] = is_outright
            else:
                cur_outright = result_is_outright[contract_month]
                # Outright beats spread regardless of volume; same class → higher volume wins
                if is_outright and not cur_outright:
                    result[contract_month] = g
                    result_vol[contract_month] = total_vol
                    result_is_outright[contract_month] = is_outright
                elif is_outright == cur_outright and total_vol > result_vol[contract_month]:
                    result[contract_month] = g
                    result_vol[contract_month] = total_vol

        return result
