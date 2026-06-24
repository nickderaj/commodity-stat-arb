"""Unit tests for roll calendar date calculations — no DB required."""

from datetime import date
import pytest

from data.roll_calendar import _cme_wti_expiry, _ice_brent_expiry, generate_roll_calendar


class TestCMEWTIExpiry:
    def test_known_date_jan_2024(self):
        # CLG4 (Feb 2024 delivery): 3 biz days before Jan 25 2024 (Thursday)
        # Jan 25 = Thursday → 3 biz days back = Jan 22 (Monday)
        assert _cme_wti_expiry(2024, 2) == date(2024, 1, 22)

    def test_known_date_dec_2023(self):
        # CLF4 (Jan 2024 delivery): 3 biz days before Dec 25 2023
        # Dec 25 is a holiday (Christmas) → last biz day before Dec 25 = Dec 22 (Friday)
        # 3 biz days before Dec 22 = Dec 19 (Tuesday)
        result = _cme_wti_expiry(2024, 1)
        assert result == date(2023, 12, 19)

    def test_no_weekend_result(self):
        for year in range(2018, 2027):
            for month in range(1, 13):
                expiry = _cme_wti_expiry(year, month)
                assert expiry.weekday() < 5, f"CL expiry {expiry} is a weekend"


class TestICEBrentExpiry:
    def test_known_date_apr_2024(self):
        # BZJ4 (Apr 2024 delivery): last biz day of Feb 2024
        # Feb 29 2024 (leap year, Thursday) is a business day
        assert _ice_brent_expiry(2024, 4) == date(2024, 2, 29)

    def test_no_weekend_result(self):
        for year in range(2018, 2027):
            for month in range(1, 13):
                expiry = _ice_brent_expiry(year, month)
                assert expiry.weekday() < 5, f"BZ expiry {expiry} is a weekend"


class TestGenerateRollCalendar:
    def test_cl_shape(self):
        df = generate_roll_calendar("CL", 2023, 2024)
        assert len(df) == 12
        assert set(df.columns) >= {"product", "contract_month", "expiry", "last_trade_date"}

    def test_bz_shape(self):
        df = generate_roll_calendar("BZ", 2023, 2024)
        assert len(df) == 12

    def test_unsupported_product(self):
        with pytest.raises(ValueError, match="Unsupported product"):
            generate_roll_calendar("GC", 2023, 2024)
