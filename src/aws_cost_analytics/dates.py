"""UTC date helpers shared across CLI, MCP, and reconciliation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def today_utc() -> date:
    """Return today's date in UTC."""
    return datetime.now(tz=timezone.utc).date()


def calendar_month_period(reference: date | None = None) -> tuple[date, date]:
    """Inclusive start/end for the calendar month containing reference (UTC today default)."""
    ref = reference or today_utc()
    start = ref.replace(day=1)
    if ref.month == 12:
        next_month = date(ref.year + 1, 1, 1)
    else:
        next_month = date(ref.year, ref.month + 1, 1)
    end = next_month - timedelta(days=1)
    return start, end


def is_full_calendar_month(start: date, end: date) -> bool:
    """Return True when start/end span a complete calendar month."""
    month_start, month_end = calendar_month_period(end)
    return start == month_start and end == month_end


def ce_end_exclusive(end: date) -> str:
    """Cost Explorer exclusive end date (day after inclusive end)."""
    return (end + timedelta(days=1)).isoformat()
