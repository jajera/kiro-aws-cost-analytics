"""Billing reconciliation: gross vs net costs and record-type breakdown.

The AWS Billing dashboard "Cost and usage" widget typically shows gross
spend before credits. Cost Explorer UnblendedCost net totals include credits,
which can make tool output appear much lower (e.g. $0.45 net vs $16.03 gross).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from aws_cost_analytics.dates import (
    calendar_month_period,
    ce_end_exclusive,
    is_full_calendar_month,
)

_ce_end_exclusive = ce_end_exclusive

__all__ = [
    "KiroSummary",
    "ReconciliationError",
    "RecordTypeSummary",
    "calendar_month_period",
    "format_reconciliation",
    "get_gross_service_breakdown",
    "get_kiro_summary",
    "get_record_type_summary",
    "get_service_gross_breakdown",
    "is_full_calendar_month",
]


class ReconciliationError(Exception):
    """Raised when reconciliation queries fail."""

    pass


@dataclass
class RecordTypeSummary:
    record_types: dict[str, float]
    gross_before_credits: float
    credits: float
    net_total: float


@dataclass
class KiroSummary:
    subscription: float
    credits: float
    usage: float
    net_total: float
    usage_type: str | None


def _sum_groups(response: dict[str, Any]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for period in response.get("ResultsByTime", []):
        for group in period.get("Groups", []):
            key = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            totals[key] = totals.get(key, 0.0) + amount
    return totals


def _sum_total(response: dict[str, Any]) -> float:
    total = 0.0
    for period in response.get("ResultsByTime", []):
        amount = (
            period.get("Total", {})
            .get("UnblendedCost", {})
            .get("Amount", "0")
        )
        total += float(amount)
    return total


def get_record_type_summary(
    ce_client, start: date, end: date
) -> RecordTypeSummary:
    """Return account-level totals grouped by RECORD_TYPE."""
    try:
        response = ce_client.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": _ce_end_exclusive(end)},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "RECORD_TYPE"}],
        )
    except (BotoCoreError, ClientError) as exc:
        raise ReconciliationError(f"Failed to query record types: {exc}") from exc

    record_types = _sum_groups(response)
    credits = record_types.get("Credit", 0.0)
    net_total = sum(record_types.values())
    gross_before_credits = net_total - credits
    return RecordTypeSummary(
        record_types=record_types,
        gross_before_credits=gross_before_credits,
        credits=credits,
        net_total=net_total,
    )


def get_service_gross_breakdown(
    ce_client, start: date, end: date, record_type: str
) -> list[tuple[str, float]]:
    """Return per-service gross amounts for a record type (e.g. Usage)."""
    try:
        response = ce_client.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": _ce_end_exclusive(end)},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            Filter={"Dimensions": {"Key": "RECORD_TYPE", "Values": [record_type]}},
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
    except (BotoCoreError, ClientError) as exc:
        raise ReconciliationError(
            f"Failed to query services for {record_type}: {exc}"
        ) from exc

    totals = _sum_groups(response)
    rows = [(name, amt) for name, amt in totals.items() if abs(amt) > 1e-8]
    rows.sort(key=lambda item: item[1], reverse=True)
    return rows


def get_gross_service_breakdown(
    ce_client, start: date, end: date
) -> list[tuple[str, float]]:
    """Return per-service gross amounts excluding credits (dashboard bar chart)."""
    try:
        response = ce_client.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": _ce_end_exclusive(end)},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            Filter={
                "Not": {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit"]}}
            },
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
    except (BotoCoreError, ClientError) as exc:
        raise ReconciliationError(
            f"Failed to query gross services: {exc}"
        ) from exc

    totals = _sum_groups(response)
    rows = [(name, amt) for name, amt in totals.items() if abs(amt) > 1e-8]
    rows.sort(key=lambda item: item[1], reverse=True)
    return rows


def get_kiro_summary(ce_client, start: date, end: date) -> KiroSummary:
    """Return Kiro subscription, credits, usage, and net totals."""
    time_period = {
        "Start": start.isoformat(),
        "End": _ce_end_exclusive(end),
    }
    kiro_filter = {"Dimensions": {"Key": "SERVICE", "Values": ["Kiro"]}}
    try:
        by_record = ce_client.get_cost_and_usage(
            TimePeriod=time_period,
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            Filter=kiro_filter,
            GroupBy=[{"Type": "DIMENSION", "Key": "RECORD_TYPE"}],
        )
        by_usage_type = ce_client.get_cost_and_usage(
            TimePeriod=time_period,
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            Filter={
                "And": [
                    kiro_filter,
                    {
                        "Dimensions": {
                            "Key": "RECORD_TYPE",
                            "Values": ["FlatRateSubscription"],
                        }
                    },
                ]
            },
            GroupBy=[{"Type": "DIMENSION", "Key": "USAGE_TYPE"}],
        )
    except (BotoCoreError, ClientError) as exc:
        raise ReconciliationError(f"Failed to query Kiro costs: {exc}") from exc

    record_types = _sum_groups(by_record)
    usage_types = _sum_groups(by_usage_type)
    usage_type = next(iter(usage_types.keys()), None)

    subscription = record_types.get("FlatRateSubscription", 0.0)
    credits = record_types.get("Credit", 0.0)
    usage = record_types.get("Usage", 0.0)
    net_total = sum(record_types.values())

    return KiroSummary(
        subscription=subscription,
        credits=credits,
        usage=usage,
        net_total=net_total,
        usage_type=usage_type,
    )


def format_reconciliation(
    account_id: str,
    start: date,
    end: date,
    record_summary: RecordTypeSummary,
    kiro_summary: KiroSummary,
    usage_services: list[tuple[str, float]],
    gross_services: list[tuple[str, float]],
    bedrock_net: float,
    *,
    dashboard_aligned: bool,
) -> str:
    """Format reconciliation output as markdown."""
    period_note = (
        "Period matches the Billing dashboard **Cost and usage** widget "
        "(full calendar month)."
        if dashboard_aligned
        else (
            "Period is partial or rolling — dashboard widget uses the **full "
            "calendar month** (e.g. Kiro subscription shows ~$13.70 for June, "
            "not prorated MTD). Re-run with no date args to align."
        )
    )
    lines = [
        f"Account {account_id} | {start.isoformat()} → {end.isoformat()}",
        "",
        period_note,
        "",
        "## Dashboard vs tool totals",
        "",
        "The Billing console **Cost and usage** widget shows **gross spend before credits**.",
        "Existing Bedrock/Kiro tools show **net UnblendedCost after credits**.",
        "",
        f"- **Gross before credits (dashboard-like):** ${record_summary.gross_before_credits:.2f} USD",
        f"- **Credits applied:** ${record_summary.credits:.2f} USD",
        f"- **Net total (tool default):** ${record_summary.net_total:.2f} USD",
        f"- **Bedrock ecosystem net:** ${bedrock_net:.2f} USD",
        "",
        "## Record type breakdown",
        "",
        "| Record type | Amount (USD) |",
        "| --- | --- |",
    ]

    for record_type, amount in sorted(
        record_summary.record_types.items(),
        key=lambda item: abs(item[1]),
        reverse=True,
    ):
        if abs(amount) > 1e-8:
            lines.append(f"| {record_type} | {amount:.2f} |")

    lines.extend(
        [
            "",
            "## Kiro (matches dashboard Kiro bar when credits are excluded)",
            "",
            f"- Subscription gross: ${kiro_summary.subscription:.2f} USD"
            + (
                f" (`{kiro_summary.usage_type}`)"
                if kiro_summary.usage_type
                else ""
            ),
            f"- Kiro credits: ${kiro_summary.credits:.2f} USD",
            f"- Kiro usage: ${kiro_summary.usage:.2f} USD",
            f"- **Kiro net:** ${kiro_summary.net_total:.2f} USD",
            "",
            "## Gross by service (dashboard bar chart, pre-credit)",
            "",
            "| Service | Amount (USD) |",
            "| --- | --- |",
        ]
    )

    for service, amount in gross_services[:15]:
        lines.append(f"| {service} | {amount:.2f} |")

    lines.extend(
        [
            "",
            "## Usage charges by service (Usage record type only)",
            "",
            "| Service | Amount (USD) |",
            "| --- | --- |",
        ]
    )

    for service, amount in usage_services[:15]:
        lines.append(f"| {service} | {amount:.2f} |")

    return "\n".join(lines)
