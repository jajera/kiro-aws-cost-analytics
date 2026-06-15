"""Command-line interface for AWS Cost Analytics.

Exposes subcommands matching the MCP tools:
- get-cost-summary
- get-cost-by-usage-type
- get-cost-by-region
- get-cost-trend
- get-kiro-cost-summary
- reconcile-billing

Accepts --start-time, --end-time, and --days parameters. The --days
parameter is a CLI convenience that converts to start_time/end_time
before calling the shared tool functions.

Uses asyncio.run() to invoke the async tool functions, producing
identical output to the MCP server interface.
"""

import argparse
import asyncio
import sys
from datetime import timedelta

from aws_cost_analytics.constants import (
    BILLING_TOOL_NAMES,
    MAX_ROLLING_DAYS,
    MIN_ROLLING_DAYS,
)
from aws_cost_analytics.dates import today_utc
from aws_cost_analytics.server import (
    tool_get_cost_by_region,
    tool_get_cost_by_usage_type,
    tool_get_cost_summary,
    tool_get_cost_trend,
    tool_get_kiro_cost_summary,
    tool_reconcile_billing,
)


def _today_utc() -> str:
    return today_utc().isoformat()


def _validate_days(days: int) -> None:
    if days < MIN_ROLLING_DAYS or days > MAX_ROLLING_DAYS:
        raise ValueError(
            f"Invalid --days value: {days}. "
            f"Accepted range: {MIN_ROLLING_DAYS} to {MAX_ROLLING_DAYS} inclusive."
        )


def _resolve_dates(args: argparse.Namespace) -> tuple[str | None, str | None]:
    if args.days is not None:
        if args.start_time or args.end_time:
            raise ValueError(
                "--days cannot be combined with --start-time or --end-time"
            )
        _validate_days(args.days)
        today = today_utc()
        start = (today - timedelta(days=args.days)).isoformat()
        end = today.isoformat()
        return start, end
    return args.start_time, args.end_time


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aws-cost-analytics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_shared_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--start-time", dest="start_time", default=None)
        subparser.add_argument("--end-time", dest="end_time", default=None)
        subparser.add_argument("--days", type=int, default=None)

    summary = subparsers.add_parser(
        "get-cost-summary", help="Get total Bedrock spend for a period"
    )
    add_shared_args(summary)

    usage_type = subparsers.add_parser(
        "get-cost-by-usage-type", help="Get Bedrock spend by usage type"
    )
    add_shared_args(usage_type)

    region = subparsers.add_parser(
        "get-cost-by-region", help="Get Bedrock spend by region"
    )
    add_shared_args(region)

    trend = subparsers.add_parser(
        "get-cost-trend", help="Get Bedrock spend as a time series"
    )
    add_shared_args(trend)
    trend.add_argument(
        "--granularity",
        choices=["DAILY", "MONTHLY"],
        default="DAILY",
    )
    trend.add_argument(
        "--group-by",
        dest="group_by",
        choices=["USAGE_TYPE", "REGION"],
        default=None,
    )

    kiro = subparsers.add_parser(
        "get-kiro-cost-summary", help="Get Kiro subscription, credits, and net spend"
    )
    add_shared_args(kiro)

    reconcile = subparsers.add_parser(
        "reconcile-billing",
        help="Reconcile dashboard gross spend vs net tool totals",
    )
    add_shared_args(reconcile)
    reconcile.epilog = (
        "Defaults to the full current calendar month (matches Billing dashboard). "
        "--days is ignored; use --start-time/--end-time for a custom range."
    )

    return parser


async def _run_command(args: argparse.Namespace) -> str:
    billing_commands = BILLING_TOOL_NAMES
    if args.command in billing_commands:
        if args.days is not None:
            if args.start_time or args.end_time:
                raise ValueError(
                    "--days cannot be combined with --start-time or --end-time"
                )
            # Billing tools default to calendar month in server; --days is ignored.
            start_time, end_time = None, None
        else:
            start_time, end_time = args.start_time, args.end_time
    else:
        start_time, end_time = _resolve_dates(args)

    if args.command == "get-cost-summary":
        return await tool_get_cost_summary(start_time, end_time)
    if args.command == "get-cost-by-usage-type":
        return await tool_get_cost_by_usage_type(start_time, end_time)
    if args.command == "get-cost-by-region":
        return await tool_get_cost_by_region(start_time, end_time)
    if args.command == "get-cost-trend":
        return await tool_get_cost_trend(
            start_time,
            end_time,
            granularity=args.granularity,
            group_by=args.group_by,
        )
    if args.command == "get-kiro-cost-summary":
        return await tool_get_kiro_cost_summary(start_time, end_time)
    if args.command == "reconcile-billing":
        return await tool_reconcile_billing(start_time, end_time)
    raise ValueError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        result = asyncio.run(_run_command(args))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if result.startswith("Error:"):
        print(result, file=sys.stderr)
        sys.exit(1)

    print(result)
    sys.exit(0)


if __name__ == "__main__":
    main()
