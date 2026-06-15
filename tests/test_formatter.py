"""Unit tests for formatter edge cases.

Tests cover Requirements 9.1–9.6:
- Zero-result output message
- Exactly 50 rows (no truncation)
- 51 rows (truncation with footer)
- Amount rounding (2dp)
- Summary line format matches spec
"""

from datetime import date

import pytest

from aws_cost_analytics.formatter import (
    MAX_ROWS,
    NO_DATA_MESSAGE,
    TRUNCATION_FOOTER,
    Formatter,
)

ACCOUNT_ID = "123456789012"
START = date(2024, 1, 1)
END = date(2024, 1, 31)


def _ungrouped_response(amounts: list[str]) -> dict:
    return {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": f"2024-01-{i+1:02d}", "End": f"2024-01-{i+2:02d}"},
                "Total": {"UnblendedCost": {"Amount": amt, "Unit": "USD"}},
            }
            for i, amt in enumerate(amounts)
        ]
    }


def _grouped_response(groups: list[tuple[str, str]]) -> dict:
    """Single period with multiple groups."""
    return {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2024-01-01", "End": "2024-01-02"},
                "Groups": [
                    {
                        "Keys": [name],
                        "Metrics": {"UnblendedCost": {"Amount": amt, "Unit": "USD"}},
                    }
                    for name, amt in groups
                ],
            }
        ]
    }


class TestZeroResults:
    def test_empty_results_by_time(self):
        fmt = Formatter()
        result = fmt.format_summary(ACCOUNT_ID, START, END, {"ResultsByTime": []})
        assert result == NO_DATA_MESSAGE

    def test_all_zero_grouped(self):
        fmt = Formatter()
        result = fmt.format_table(
            ACCOUNT_ID,
            START,
            END,
            _grouped_response([("type-a", "0.00"), ("type-b", "0.00")]),
            columns=["Usage Type", "Amount (USD)"],
        )
        assert result == NO_DATA_MESSAGE


class TestSummaryLine:
    def test_summary_format(self):
        fmt = Formatter()
        results = _ungrouped_response(["10.50", "20.333"])
        output = fmt.format_summary(ACCOUNT_ID, START, END, results)
        assert output == (
            f"Account {ACCOUNT_ID} | 2024-01-01 \u2192 2024-01-31 | Total: $30.83 USD"
        )

    def test_summary_rounds_to_two_decimal_places(self):
        fmt = Formatter()
        results = _ungrouped_response(["1.005", "2.004"])
        output = fmt.format_summary(ACCOUNT_ID, START, END, results)
        assert "Total: $3.01 USD" in output


class TestTruncation:
    def test_exactly_max_rows_no_footer(self):
        fmt = Formatter()
        groups = [(f"type-{i}", f"{i + 1}.00") for i in range(MAX_ROWS)]
        output = fmt.format_table(
            ACCOUNT_ID,
            START,
            END,
            _grouped_response(groups),
            columns=["Usage Type", "Amount (USD)"],
        )
        assert TRUNCATION_FOOTER not in output
        assert output.count("| type-") == MAX_ROWS

    def test_fifty_one_rows_truncates_with_footer(self):
        fmt = Formatter()
        groups = [(f"type-{i}", f"{100 - i}.00") for i in range(51)]
        output = fmt.format_table(
            ACCOUNT_ID,
            START,
            END,
            _grouped_response(groups),
            columns=["Usage Type", "Amount (USD)"],
        )
        assert TRUNCATION_FOOTER in output
        assert output.count("| type-") == MAX_ROWS

    def test_trend_truncation(self):
        fmt = Formatter()
        amounts = [f"{i + 1}.00" for i in range(51)]
        output = fmt.format_trend(
            ACCOUNT_ID, START, END, _ungrouped_response(amounts)
        )
        assert TRUNCATION_FOOTER in output
        data_rows = [
            line for line in output.splitlines() if line.startswith("| 2024-")
        ]
        assert len(data_rows) == MAX_ROWS


class TestGroupedTable:
    def test_sorted_descending(self):
        fmt = Formatter()
        results = _grouped_response(
            [("low", "1.00"), ("high", "99.00"), ("mid", "50.00")]
        )
        output = fmt.format_table(
            ACCOUNT_ID,
            START,
            END,
            results,
            columns=["Usage Type", "Amount (USD)"],
        )
        lines = [line for line in output.splitlines() if line.startswith("| high")]
        assert lines
        high_idx = output.index("| high")
        mid_idx = output.index("| mid")
        low_idx = output.index("| low")
        assert high_idx < mid_idx < low_idx
