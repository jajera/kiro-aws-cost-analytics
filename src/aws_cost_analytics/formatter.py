"""Output formatting and truncation.

Converts raw Cost Explorer responses into pipe-delimited markdown tables
with summary lines. Supports three output modes:
- Summary: total spend with account ID and date range
- Grouped table: aggregated by dimension, sorted by amount descending
- Trend table: chronological time series with optional group column

Output is truncated at 50 data rows with a footer message when exceeded.
All USD amounts are formatted to 2 decimal places.
"""

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

MAX_ROWS = 50
TRUNCATION_FOOTER = "Narrow date range or use a specific group-by"

NO_DATA_MESSAGE = "No cost data found for the period"

_TWO_PLACES = Decimal("0.01")


def quantize_money(amount: Decimal) -> Decimal:
    """Round a money amount to two decimal places (half-up)."""
    return amount.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _parse_amount(amount_str: str) -> Decimal:
    return Decimal(amount_str)


def _format_money(amount: Decimal) -> str:
    return f"{quantize_money(amount):.2f}"


class Formatter:
    """Formats Cost Explorer responses into markdown output."""

    def _compute_total(self, results: dict) -> Decimal:
        """Sum Amount values across all ResultsByTime entries.

        Handles both ungrouped (Total) and grouped (Groups) response formats.

        Args:
            results: Raw Cost Explorer response dict.

        Returns:
            Total amount as a Decimal.
        """
        total = Decimal("0")
        for period in results.get("ResultsByTime", []):
            if "Groups" in period and period["Groups"]:
                for group in period["Groups"]:
                    amount_str = group["Metrics"]["UnblendedCost"]["Amount"]
                    total += _parse_amount(amount_str)
            elif "Total" in period:
                amount_str = period["Total"]["UnblendedCost"]["Amount"]
                total += _parse_amount(amount_str)
        return total

    def _format_summary_line(
        self, account_id: str, start: date, end: date, total: Decimal
    ) -> str:
        """Produce the summary line.

        Format: "Account {id} | {start} → {end} | Total: ${amount} USD"
        """
        return (
            f"Account {account_id} | {start.isoformat()} \u2192 {end.isoformat()} "
            f"| Total: ${_format_money(total)} USD"
        )

    def format_summary(
        self, account_id: str, start: date, end: date, results: dict
    ) -> str:
        """Sum Amount across all ResultsByTime, round to 2dp.

        Args:
            account_id: The 12-digit AWS account ID.
            start: Inclusive start date (user-facing).
            end: Inclusive end date (user-facing).
            results: Raw Cost Explorer response dict.

        Returns:
            Summary line string.
        """
        results_by_time = results.get("ResultsByTime", [])
        if not results_by_time:
            return NO_DATA_MESSAGE

        total = self._compute_total(results)
        return self._format_summary_line(account_id, start, end, total)

    def format_table(
        self,
        account_id: str,
        start: date,
        end: date,
        results: dict,
        columns: list[str],
        group_key: Optional[str] = None,
    ) -> str:
        """Produce summary line + markdown table aggregated by group.

        Aggregates costs across all time periods by unique group value,
        sorts rows by amount descending, and truncates at MAX_ROWS.

        Args:
            account_id: The 12-digit AWS account ID.
            start: Inclusive start date (user-facing).
            end: Inclusive end date (user-facing).
            results: Raw Cost Explorer response dict.
            columns: Column headers for the table (e.g., ["Usage Type", "Amount (USD)"]).
            group_key: Optional group-by key name (for labeling).

        Returns:
            Formatted markdown string with summary line and table.
        """
        results_by_time = results.get("ResultsByTime", [])
        if not results_by_time:
            return NO_DATA_MESSAGE

        # Aggregate amounts by group value across all time periods
        aggregated: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for period in results_by_time:
            groups = period.get("Groups", [])
            for group in groups:
                key_value = group["Keys"][0]
                amount = _parse_amount(group["Metrics"]["UnblendedCost"]["Amount"])
                aggregated[key_value] += amount

        # Check for zero-result case (all amounts are zero or no groups)
        if not aggregated or all(v == 0 for v in aggregated.values()):
            return NO_DATA_MESSAGE

        # Sort by amount descending
        sorted_rows = sorted(aggregated.items(), key=lambda x: x[1], reverse=True)

        # Compute total for summary
        total = self._compute_total(results)
        summary_line = self._format_summary_line(account_id, start, end, total)

        # Build markdown table
        header = "| " + " | ".join(columns) + " |"
        separator = "| " + " | ".join(["---"] * len(columns)) + " |"

        lines = [summary_line, "", header, separator]

        # Determine if truncation is needed
        truncated = len(sorted_rows) > MAX_ROWS
        display_rows = sorted_rows[:MAX_ROWS]

        for key_value, amount in display_rows:
            lines.append(f"| {key_value} | {_format_money(amount)} |")

        if truncated:
            lines.append("")
            lines.append(TRUNCATION_FOOTER)

        return "\n".join(lines)

    def format_trend(
        self,
        account_id: str,
        start: date,
        end: date,
        results: dict,
        group_key: Optional[str] = None,
    ) -> str:
        """Produce summary line + chronological trend table.

        One row per time period (ungrouped) or per time period × group
        (grouped). Rows are in chronological order (CE natural order).
        Truncates at MAX_ROWS.

        Args:
            account_id: The 12-digit AWS account ID.
            start: Inclusive start date (user-facing).
            end: Inclusive end date (user-facing).
            results: Raw Cost Explorer response dict.
            group_key: Optional group-by dimension name for column header.

        Returns:
            Formatted markdown string with summary line and table.
        """
        results_by_time = results.get("ResultsByTime", [])
        if not results_by_time:
            return NO_DATA_MESSAGE

        # Compute total for summary
        total = self._compute_total(results)
        summary_line = self._format_summary_line(account_id, start, end, total)

        # Determine if grouped or ungrouped
        is_grouped = group_key is not None

        # Build rows in chronological order
        rows: list[tuple] = []
        for period in results_by_time:
            period_start = period["TimePeriod"]["Start"]
            if is_grouped:
                groups = period.get("Groups", [])
                for group in groups:
                    key_value = group["Keys"][0]
                    amount = _parse_amount(group["Metrics"]["UnblendedCost"]["Amount"])
                    rows.append((period_start, key_value, amount))
            else:
                # Ungrouped — use Total
                if "Total" in period:
                    amount = _parse_amount(period["Total"]["UnblendedCost"]["Amount"])
                else:
                    amount = Decimal("0")
                rows.append((period_start, amount))

        # Check for zero-result (all amounts zero)
        if is_grouped:
            all_zero = all(row[2] == 0 for row in rows)
        else:
            all_zero = all(row[1] == 0 for row in rows)

        if not rows or all_zero:
            return NO_DATA_MESSAGE

        # Build markdown table headers
        if is_grouped:
            # Use the group_key as column name (e.g., "Usage Type" or "Region")
            group_col_name = _dimension_to_column_name(group_key)
            columns = ["Date", group_col_name, "Amount (USD)"]
        else:
            columns = ["Date", "Amount (USD)"]

        header = "| " + " | ".join(columns) + " |"
        separator = "| " + " | ".join(["---"] * len(columns)) + " |"

        lines = [summary_line, "", header, separator]

        # Determine if truncation is needed
        truncated = len(rows) > MAX_ROWS
        display_rows = rows[:MAX_ROWS]

        for row in display_rows:
            if is_grouped:
                period_start, key_value, amount = row
                lines.append(
                    f"| {period_start} | {key_value} | {_format_money(amount)} |"
                )
            else:
                period_start, amount = row
                lines.append(f"| {period_start} | {_format_money(amount)} |")

        if truncated:
            lines.append("")
            lines.append(TRUNCATION_FOOTER)

        return "\n".join(lines)


def _dimension_to_column_name(group_key: str) -> str:
    """Convert a CE dimension key to a human-readable column name.

    Args:
        group_key: The CE dimension key (e.g., "USAGE_TYPE", "REGION").

    Returns:
        Human-readable column name.
    """
    mapping = {
        "USAGE_TYPE": "Usage Type",
        "REGION": "Region",
    }
    return mapping.get(group_key, group_key)
