"""Tests for shared date helpers."""

from datetime import date

from aws_cost_analytics.dates import (
    calendar_month_period,
    ce_end_exclusive,
    is_full_calendar_month,
)


def test_calendar_month_period_june():
    start, end = calendar_month_period(date(2026, 6, 15))
    assert start == date(2026, 6, 1)
    assert end == date(2026, 6, 30)


def test_is_full_calendar_month():
    assert is_full_calendar_month(date(2026, 6, 1), date(2026, 6, 30))
    assert not is_full_calendar_month(date(2026, 6, 1), date(2026, 6, 15))


def test_ce_end_exclusive():
    assert ce_end_exclusive(date(2026, 6, 30)) == "2026-07-01"
