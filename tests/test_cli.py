"""Unit tests for CLI argument parsing and integration.

Tests cover Requirements 11.1–11.10:
- Subcommand registration (6 subcommands)
- --days mutual exclusivity with --start-time/--end-time
- --days range validation (0 rejected, 366 rejected, 1 and 365 accepted)
- --granularity and --group-by on get-cost-trend only
- Exit codes (0 on success, non-zero on error)
"""

import argparse
import sys
from unittest.mock import AsyncMock, patch

import pytest

from aws_cost_analytics.constants import TOOL_NAMES
from aws_cost_analytics.cli import _build_parser, main


class TestSubcommandRegistration:
    def test_six_subcommands_registered(self):
        parser = _build_parser()
        subparsers_action = next(
            a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
        )
        subcommands = list(subparsers_action.choices.keys())
        assert set(subcommands) == TOOL_NAMES

    def test_trend_has_granularity_and_group_by(self):
        parser = _build_parser()
        args = parser.parse_args(
            ["get-cost-trend", "--granularity", "MONTHLY", "--group-by", "REGION"]
        )
        assert args.granularity == "MONTHLY"
        assert args.group_by == "REGION"


class TestDaysMutualExclusivity:
    def test_days_with_start_time_rejected(self):
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "get-cost-summary",
                    "--days",
                    "7",
                    "--start-time",
                    "2024-01-01",
                ]
            )
        assert exc.value.code != 0

    def test_days_with_end_time_rejected(self):
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "get-cost-summary",
                    "--days",
                    "7",
                    "--end-time",
                    "2024-01-31",
                ]
            )
        assert exc.value.code != 0


class TestDaysRangeValidation:
    @pytest.mark.parametrize("days", [0, 366, -1])
    def test_invalid_days_rejected(self, days: int):
        with pytest.raises(SystemExit) as exc:
            main(["get-cost-summary", "--days", str(days)])
        assert exc.value.code != 0

    @pytest.mark.parametrize("days", [1, 365])
    def test_valid_days_accepted(self, days: int):
        with patch(
            "aws_cost_analytics.cli.tool_get_cost_summary",
            new_callable=AsyncMock,
            return_value="Account 123 | 2024-01-01 → 2024-01-31 | Total: $1.00 USD",
        ):
            with pytest.raises(SystemExit) as exc:
                main(["get-cost-summary", "--days", str(days)])
            assert exc.value.code == 0


class TestExitCodes:
    def test_success_exit_zero(self, capsys):
        with patch(
            "aws_cost_analytics.cli.tool_get_cost_summary",
            new_callable=AsyncMock,
            return_value="ok",
        ):
            with pytest.raises(SystemExit) as exc:
                main(["get-cost-summary"])
        assert exc.value.code == 0
        assert capsys.readouterr().out.strip() == "ok"

    def test_tool_error_exit_nonzero(self, capsys):
        with patch(
            "aws_cost_analytics.cli.tool_get_cost_summary",
            new_callable=AsyncMock,
            return_value="Error: something failed",
        ):
            with pytest.raises(SystemExit) as exc:
                main(["get-cost-summary"])
        assert exc.value.code != 0
        captured = capsys.readouterr()
        assert "Error: something failed" in captured.err

    def test_cli_validation_error_exit_nonzero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["get-cost-summary", "--days", "0"])
        assert exc.value.code != 0
        assert "Error:" in capsys.readouterr().err


class TestCommandRouting:
    def test_routes_to_correct_tool(self):
        with patch(
            "aws_cost_analytics.cli.tool_get_cost_by_usage_type",
            new_callable=AsyncMock,
            return_value="usage",
        ) as mock_tool:
            with pytest.raises(SystemExit):
                main(["get-cost-by-usage-type", "--start-time", "2024-01-01"])
        mock_tool.assert_awaited_once()

    def test_trend_passes_granularity(self):
        with patch(
            "aws_cost_analytics.cli.tool_get_cost_trend",
            new_callable=AsyncMock,
            return_value="trend",
        ) as mock_tool:
            with pytest.raises(SystemExit):
                main(
                    [
                        "get-cost-trend",
                        "--granularity",
                        "MONTHLY",
                        "--group-by",
                        "USAGE_TYPE",
                    ]
                )
        mock_tool.assert_awaited_once_with(
            None, None, granularity="MONTHLY", group_by="USAGE_TYPE"
        )
