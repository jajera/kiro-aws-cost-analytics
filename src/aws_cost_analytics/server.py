"""Shared tool functions and MCP server registration.

Contains tool functions that orchestrate the full request flow:
config → auth → validate → service discovery → guardrail → executor → formatter.

Both the CLI and MCP server import and call these functions directly,
ensuring identical behavior from both interfaces.
"""

from datetime import date, timedelta
from typing import Callable, Optional

from mcp.server.fastmcp import FastMCP

from aws_cost_analytics.auth import AuthError, AuthModule
from aws_cost_analytics.config import ConfigError, load_config
from aws_cost_analytics.constants import (
    MCP_SERVER_NAME,
    VALID_GRANULARITIES,
    VALID_GROUP_BY,
)
from aws_cost_analytics.dates import calendar_month_period, is_full_calendar_month, today_utc
from aws_cost_analytics.executors import Executor, ExecutorError
from aws_cost_analytics.formatter import Formatter
from aws_cost_analytics.guardrails import GuardrailError
from aws_cost_analytics.reconciliation import (
    ReconciliationError,
    format_reconciliation,
    get_gross_service_breakdown,
    get_kiro_summary,
    get_record_type_summary,
    get_service_gross_breakdown,
)
from aws_cost_analytics.services import (
    ServiceDiscoveryError,
    prepare_bedrock_cost_filter,
)

mcp_server = FastMCP(MCP_SERVER_NAME)


def _today_utc() -> date:
    return today_utc()


def _parse_query_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"Invalid {field_name}: '{value}'. "
            "Expected a valid calendar date in YYYY-MM-DD format."
        ) from exc


def _validate_dates(
    start_time: Optional[str], end_time: Optional[str]
) -> tuple[date, date]:
    today = _today_utc()
    start = (
        _parse_query_date(start_time, "start_time")
        if start_time is not None
        else today - timedelta(days=30)
    )
    end = (
        _parse_query_date(end_time, "end_time")
        if end_time is not None
        else today
    )
    if start > end:
        raise ValueError(
            f"start_time ({start.isoformat()}) must not be later than "
            f"end_time ({end.isoformat()})"
        )
    return start, end


def _validate_billing_dates(
    start_time: Optional[str], end_time: Optional[str]
) -> tuple[date, date, bool]:
    """Resolve dates for dashboard-aligned billing tools.

    Defaults to the full current calendar month (matches Billing console widget).
    Returns (start, end, dashboard_aligned).
    """
    today = _today_utc()
    if start_time is None and end_time is None:
        start, end = calendar_month_period(today)
        return start, end, True

    start = (
        _parse_query_date(start_time, "start_time")
        if start_time is not None
        else calendar_month_period(
            _parse_query_date(end_time, "end_time") if end_time else today
        )[0]
    )
    end = (
        _parse_query_date(end_time, "end_time")
        if end_time is not None
        else calendar_month_period(start)[1]
    )
    if start > end:
        raise ValueError(
            f"start_time ({start.isoformat()}) must not be later than "
            f"end_time ({end.isoformat()})"
        )
    return start, end, is_full_calendar_month(start, end)


def _validate_granularity(value: str) -> str:
    if value not in VALID_GRANULARITIES:
        raise ValueError(
            f"Invalid granularity: '{value}'. Accepted values: DAILY, MONTHLY"
        )
    return value


def _validate_group_by(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if value not in VALID_GROUP_BY:
        raise ValueError(
            f"Invalid group_by: '{value}'. Accepted values: USAGE_TYPE, REGION"
        )
    return value


def _group_by_dict(dimension: Optional[str]) -> Optional[dict]:
    if dimension is None:
        return None
    return {"Type": "DIMENSION", "Key": dimension}


def _format_error(exc: Exception) -> str:
    return f"Error: {exc}"


async def _run_bedrock_tool(
    start_time: Optional[str],
    end_time: Optional[str],
    cache_tool: str,
    format_fn: Callable[[str, date, date, dict], str],
    granularity: str = "DAILY",
    group_by: Optional[str] = None,
) -> str:
    start, end = _validate_dates(start_time, end_time)
    config = load_config()
    auth = AuthModule(config.region).get_credentials()
    executor = Executor(auth.session, auth.account_id, config.cache_ttl_hours)
    service_filter, cache_scope = prepare_bedrock_cost_filter(
        executor._ce_client, config.cache_ttl_hours
    )
    group_by_dict = _group_by_dict(group_by)
    results = executor.get_cost_and_usage(
        start,
        end,
        granularity=granularity,
        group_by=group_by_dict,
        cache_tool=cache_tool,
        service_filter=service_filter,
        cache_scope=cache_scope,
    )
    return format_fn(auth.account_id, start, end, results)


@mcp_server.tool(name="get-cost-summary")
async def tool_get_cost_summary(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> str:
    """Get total Bedrock ecosystem spend for the given period."""
    try:
        return await _run_bedrock_tool(
            start_time,
            end_time,
            cache_tool="cost-summary",
            format_fn=Formatter().format_summary,
        )
    except (
        ConfigError,
        AuthError,
        GuardrailError,
        ExecutorError,
        ServiceDiscoveryError,
        ValueError,
    ) as exc:
        return _format_error(exc)


@mcp_server.tool(name="get-cost-by-usage-type")
async def tool_get_cost_by_usage_type(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> str:
    """Get Bedrock ecosystem spend broken down by usage type."""
    try:
        formatter = Formatter()
        return await _run_bedrock_tool(
            start_time,
            end_time,
            cache_tool="cost-by-usage-type",
            format_fn=lambda account_id, start, end, results: formatter.format_table(
                account_id,
                start,
                end,
                results,
                columns=["Usage Type", "Amount (USD)"],
                group_key="USAGE_TYPE",
            ),
            group_by="USAGE_TYPE",
        )
    except (
        ConfigError,
        AuthError,
        GuardrailError,
        ExecutorError,
        ServiceDiscoveryError,
        ValueError,
    ) as exc:
        return _format_error(exc)


@mcp_server.tool(name="get-cost-by-region")
async def tool_get_cost_by_region(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> str:
    """Get Bedrock ecosystem spend broken down by region."""
    try:
        formatter = Formatter()
        return await _run_bedrock_tool(
            start_time,
            end_time,
            cache_tool="cost-by-region",
            format_fn=lambda account_id, start, end, results: formatter.format_table(
                account_id,
                start,
                end,
                results,
                columns=["Region", "Amount (USD)"],
                group_key="REGION",
            ),
            group_by="REGION",
        )
    except (
        ConfigError,
        AuthError,
        GuardrailError,
        ExecutorError,
        ServiceDiscoveryError,
        ValueError,
    ) as exc:
        return _format_error(exc)


@mcp_server.tool(name="get-cost-trend")
async def tool_get_cost_trend(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    granularity: str = "DAILY",
    group_by: Optional[str] = None,
) -> str:
    """Get Bedrock ecosystem spend as a time series (daily or monthly)."""
    try:
        granularity = _validate_granularity(granularity)
        group_by = _validate_group_by(group_by)
        formatter = Formatter()
        return await _run_bedrock_tool(
            start_time,
            end_time,
            cache_tool="cost-trend",
            format_fn=lambda account_id, start, end, results: formatter.format_trend(
                account_id, start, end, results, group_key=group_by
            ),
            granularity=granularity,
            group_by=group_by,
        )
    except (
        ConfigError,
        AuthError,
        GuardrailError,
        ExecutorError,
        ServiceDiscoveryError,
        ValueError,
    ) as exc:
        return _format_error(exc)


@mcp_server.tool(name="get-kiro-cost-summary")
async def tool_get_kiro_cost_summary(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> str:
    """Get Kiro subscription, credits, and net spend for the period."""
    try:
        start, end, _ = _validate_billing_dates(start_time, end_time)
        config = load_config()
        auth = AuthModule(config.region).get_credentials()
        executor = Executor(auth.session, auth.account_id, config.cache_ttl_hours)
        kiro = get_kiro_summary(executor._ce_client, start, end)

        lines = [
            f"Account {auth.account_id} | {start.isoformat()} → {end.isoformat()}",
            "",
            "Kiro billing (SERVICE = Kiro):",
            "",
            f"- Subscription (gross): ${kiro.subscription:.2f} USD"
            + (f" — {kiro.usage_type}" if kiro.usage_type else ""),
            f"- Credits: ${kiro.credits:.2f} USD",
            f"- Usage: ${kiro.usage:.2f} USD",
            f"- **Net total: ${kiro.net_total:.2f} USD**",
            "",
            "Note: The Billing dashboard Kiro bar shows subscription gross "
            "before credits. Net is $0.00 when credits fully offset subscription.",
        ]
        return "\n".join(lines)
    except (
        ConfigError,
        AuthError,
        ReconciliationError,
        ValueError,
    ) as exc:
        return _format_error(exc)


@mcp_server.tool(name="reconcile-billing")
async def tool_reconcile_billing(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> str:
    """Reconcile dashboard gross spend vs net tool totals with record-type breakdown."""
    try:
        start, end, dashboard_aligned = _validate_billing_dates(
            start_time, end_time
        )
        config = load_config()
        auth = AuthModule(config.region).get_credentials()
        executor = Executor(auth.session, auth.account_id, config.cache_ttl_hours)
        ce = executor._ce_client

        record_summary = get_record_type_summary(ce, start, end)
        kiro_summary = get_kiro_summary(ce, start, end)
        usage_services = get_service_gross_breakdown(ce, start, end, "Usage")
        gross_services = get_gross_service_breakdown(ce, start, end)

        service_filter, _ = prepare_bedrock_cost_filter(ce, config.cache_ttl_hours)
        bedrock_results = executor.get_cost_and_usage(
            start,
            end,
            cache_tool="cost-summary",
            service_filter=service_filter,
            cache_scope="reconcile-bedrock",
        )
        bedrock_net = Formatter()._compute_total(bedrock_results)

        return format_reconciliation(
            auth.account_id,
            start,
            end,
            record_summary,
            kiro_summary,
            usage_services,
            gross_services,
            bedrock_net,
            dashboard_aligned=dashboard_aligned,
        )
    except (
        ConfigError,
        AuthError,
        GuardrailError,
        ExecutorError,
        ServiceDiscoveryError,
        ReconciliationError,
        ValueError,
    ) as exc:
        return _format_error(exc)


def main() -> None:
    """Run the FastMCP server with stdio transport."""
    mcp_server.run(transport="stdio")
