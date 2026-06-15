"""Property-based tests for formatter module.

Tests three correctness properties from the design document:
- Property 11: Summary computation sums and rounds correctly
- Property 12: Grouped table aggregation and sort order
- Property 13: Truncation at 50 rows with footer

Validates: Requirements 5.6, 6.5, 6.6, 7.5, 7.6, 9.1, 9.3, 9.4
"""

from datetime import date
from decimal import Decimal

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from aws_cost_analytics.formatter import MAX_ROWS, TRUNCATION_FOOTER, Formatter, quantize_money

ACCOUNT_ID = "123456789012"
START = date(2024, 1, 1)
END = date(2024, 1, 31)

_amount_st = st.floats(
    min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False
)
_group_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), min_codepoint=65),
    min_size=1,
    max_size=20,
)


class TestProperty11SummaryComputation:
    """# Feature: aws-cost-analytics, Property 11: Summary computation sums and rounds correctly"""

    @settings(max_examples=100)
    @given(amounts=st.lists(_amount_st, min_size=1, max_size=20))
    def test_summary_total_matches_sum_rounded(self, amounts: list[float]):
        """**Validates: Requirements 5.6, 9.1**"""
        results = {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2024-01-01", "End": "2024-01-02"},
                    "Total": {
                        "UnblendedCost": {
                            "Amount": f"{amt:.6f}",
                            "Unit": "USD",
                        }
                    },
                }
                for amt in amounts
            ]
        }
        expected_total = quantize_money(
            sum(Decimal(f"{amt:.6f}") for amt in amounts)
        )
        output = Formatter().format_summary(ACCOUNT_ID, START, END, results)
        assert f"Account {ACCOUNT_ID}" in output
        assert "2024-01-01" in output
        assert "2024-01-31" in output
        assert f"Total: ${expected_total:.2f} USD" in output


class TestProperty12GroupedTableAggregation:
    """# Feature: aws-cost-analytics, Property 12: Grouped table aggregation and sort order"""

    @settings(max_examples=100)
    @given(
        entries=st.lists(
            st.tuples(_group_name_st, _amount_st),
            min_size=1,
            max_size=30,
            unique_by=lambda x: x[0],
        )
    )
    def test_unique_groups_aggregated_and_sorted(self, entries: list[tuple[str, float]]):
        """**Validates: Requirements 6.5, 6.6, 7.5, 7.6**"""
        assume(len(entries) <= MAX_ROWS)
        assume(all(amt >= 0.01 for _, amt in entries))

        groups = [
            {
                "Keys": [name],
                "Metrics": {"UnblendedCost": {"Amount": f"{amt:.6f}", "Unit": "USD"}},
            }
            for name, amt in entries
        ]
        results = {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2024-01-01", "End": "2024-01-02"},
                    "Groups": groups,
                },
                {
                    "TimePeriod": {"Start": "2024-01-02", "End": "2024-01-03"},
                    "Groups": [
                        {
                            "Keys": [name],
                            "Metrics": {
                                "UnblendedCost": {
                                    "Amount": f"{amt / 2:.6f}",
                                    "Unit": "USD",
                                }
                            },
                        }
                        for name, amt in entries
                    ],
                },
            ]
        }

        expected = {
            name: quantize_money(
                Decimal(f"{amt:.6f}") + Decimal(f"{amt / 2:.6f}")
            )
            for name, amt in entries
            if amt + amt / 2 > 0
        }
        assume(expected)

        output = Formatter().format_table(
            ACCOUNT_ID,
            START,
            END,
            results,
            columns=["Usage Type", "Amount (USD)"],
        )

        sorted_names = sorted(expected.keys(), key=lambda k: expected[k], reverse=True)
        table_section = output.split("|---|", 1)[-1]
        last_idx = -1
        for name in sorted_names:
            needle = f"| {name} |"
            idx = table_section.index(needle)
            assert idx > last_idx
            last_idx = idx
            row_line = next(
                line for line in table_section.splitlines() if line.startswith(needle)
            )
            assert row_line.endswith(f"| {expected[name]:.2f} |")


class TestProperty13Truncation:
    """# Feature: aws-cost-analytics, Property 13: Truncation at 50 rows with footer"""

    @settings(max_examples=50)
    @given(row_count=st.integers(min_value=51, max_value=80))
    def test_more_than_max_rows_truncates_with_footer(self, row_count: int):
        """**Validates: Requirements 9.3, 9.4**"""
        groups = [
            (f"group-{i}", f"{i + 1}.00") for i in range(row_count)
        ]
        results = {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2024-01-01", "End": "2024-01-02"},
                    "Groups": [
                        {
                            "Keys": [name],
                            "Metrics": {
                                "UnblendedCost": {"Amount": amt, "Unit": "USD"}
                            },
                        }
                        for name, amt in groups
                    ],
                }
            ]
        }
        output = Formatter().format_table(
            ACCOUNT_ID,
            START,
            END,
            results,
            columns=["Usage Type", "Amount (USD)"],
        )
        data_rows = [
            line for line in output.splitlines() if line.startswith("| group-")
        ]
        assert len(data_rows) == MAX_ROWS
        assert TRUNCATION_FOOTER in output

    @settings(max_examples=50)
    @given(row_count=st.integers(min_value=1, max_value=MAX_ROWS))
    def test_at_or_below_max_rows_no_footer(self, row_count: int):
        """**Validates: Requirements 9.3, 9.4**"""
        groups = [(f"g{i}", f"{i + 1}.00") for i in range(row_count)]
        results = {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2024-01-01", "End": "2024-01-02"},
                    "Groups": [
                        {
                            "Keys": [name],
                            "Metrics": {
                                "UnblendedCost": {"Amount": amt, "Unit": "USD"}
                            },
                        }
                        for name, amt in groups
                    ],
                }
            ]
        }
        output = Formatter().format_table(
            ACCOUNT_ID,
            START,
            END,
            results,
            columns=["Usage Type", "Amount (USD)"],
        )
        assert TRUNCATION_FOOTER not in output
