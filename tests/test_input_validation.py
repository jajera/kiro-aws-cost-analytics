"""Property-based tests for input validation in server.py.

Tests four correctness properties from the design document:
- Property 6: Date validation accepts only real calendar dates
- Property 7: Start-time must not be after end-time
- Property 8: Granularity and group_by enum validation
- Property 9: Days parameter range validation

Validates: Requirements 4.1, 4.2, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9
"""

from datetime import date, timedelta

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from aws_cost_analytics.cli import _validate_days
from aws_cost_analytics.server import (
    _parse_query_date,
    _validate_dates,
    _validate_granularity,
    _validate_group_by,
)


class TestProperty6DateValidation:
    """# Feature: aws-cost-analytics, Property 6: Date validation accepts only real calendar dates"""

    @settings(max_examples=100)
    @given(
        d=st.dates(min_value=date(2000, 1, 1), max_value=date(2030, 12, 31))
    )
    def test_valid_iso_dates_accepted(self, d: date):
        """**Validates: Requirements 4.1**"""
        parsed = _parse_query_date(d.isoformat(), "start_time")
        assert parsed == d

    @pytest.mark.parametrize(
        "invalid",
        [
            "2024-02-30",
            "2024-13-01",
            "not-a-date",
            "2024/01/01",
            "24-01-01",
        ],
    )
    def test_invalid_dates_rejected(self, invalid: str):
        """**Validates: Requirements 4.1**"""
        with pytest.raises(ValueError, match="Invalid start_time"):
            _parse_query_date(invalid, "start_time")


class TestProperty7DateOrdering:
    """# Feature: aws-cost-analytics, Property 7: Start-time must not be after end-time"""

    @settings(max_examples=100)
    @given(
        start=st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
        offset=st.integers(min_value=1, max_value=365),
    )
    def test_start_after_end_rejected(self, start: date, offset: int):
        """**Validates: Requirements 4.2**"""
        end = start - timedelta(days=offset)
        with pytest.raises(ValueError, match="must not be later than"):
            _validate_dates(start.isoformat(), end.isoformat())

    @settings(max_examples=100)
    @given(
        start=st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 6, 30)),
        offset=st.integers(min_value=0, max_value=365),
    )
    def test_start_on_or_before_end_accepted(self, start: date, offset: int):
        """**Validates: Requirements 4.2**"""
        end = start + timedelta(days=offset)
        result_start, result_end = _validate_dates(start.isoformat(), end.isoformat())
        assert result_start == start
        assert result_end == end


class TestProperty8EnumValidation:
    """# Feature: aws-cost-analytics, Property 8: Granularity and group_by enum validation"""

    @settings(max_examples=100)
    @given(value=st.sampled_from(["DAILY", "MONTHLY"]))
    def test_valid_granularity_accepted(self, value: str):
        """**Validates: Requirements 4.4, 4.5**"""
        assert _validate_granularity(value) == value

    @settings(max_examples=100)
    @given(value=st.text(min_size=1, max_size=20))
    def test_invalid_granularity_rejected(self, value: str):
        """**Validates: Requirements 4.4, 4.5**"""
        assume(value not in {"DAILY", "MONTHLY"})
        with pytest.raises(ValueError, match="Invalid granularity"):
            _validate_granularity(value)

    @settings(max_examples=100)
    @given(value=st.one_of(st.none(), st.sampled_from(["USAGE_TYPE", "REGION"])))
    def test_valid_group_by_accepted(self, value):
        """**Validates: Requirements 4.6, 4.7**"""
        assert _validate_group_by(value) == value

    @settings(max_examples=100)
    @given(value=st.text(min_size=1, max_size=20))
    def test_invalid_group_by_rejected(self, value: str):
        """**Validates: Requirements 4.6, 4.7**"""
        assume(value not in {"USAGE_TYPE", "REGION"})
        with pytest.raises(ValueError, match="Invalid group_by"):
            _validate_group_by(value)


class TestProperty9DaysValidation:
    """# Feature: aws-cost-analytics, Property 9: Days parameter range validation"""

    @settings(max_examples=100)
    @given(days=st.integers(min_value=1, max_value=365))
    def test_valid_days_accepted(self, days: int):
        """**Validates: Requirements 4.8, 4.9**"""
        _validate_days(days)

    @settings(max_examples=100)
    @given(days=st.integers().filter(lambda d: d < 1 or d > 365))
    def test_invalid_days_rejected(self, days: int):
        """**Validates: Requirements 4.8, 4.9**"""
        with pytest.raises(ValueError, match="Accepted range: 1 to 365"):
            _validate_days(days)
