"""Unit tests for server integration and MCP registration.

Tests cover Requirements 12.1, 12.4, 12.6, 13.5:
- MCP tool registration (6 tools with correct names)
- Tool invocation with mocked executor (end-to-end)
- Error handling returns user-friendly messages (no tracebacks)
- Default date calculation (today-30 to today)
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from aws_cost_analytics.auth import AuthError, AuthResult
from aws_cost_analytics.config import ConfigError
from aws_cost_analytics.executors import ExecutorError
from aws_cost_analytics.constants import TOOL_NAMES
from aws_cost_analytics.server import (
    mcp_server,
    tool_get_cost_by_region,
    tool_get_cost_by_usage_type,
    tool_get_cost_summary,
    tool_get_cost_trend,
)


MOCK_CE_RESPONSE = {
    "ResultsByTime": [
        {
            "TimePeriod": {"Start": "2024-01-01", "End": "2024-01-02"},
            "Total": {"UnblendedCost": {"Amount": "42.50", "Unit": "USD"}},
        }
    ]
}

MOCK_GROUPED_RESPONSE = {
    "ResultsByTime": [
        {
            "TimePeriod": {"Start": "2024-01-01", "End": "2024-01-02"},
            "Groups": [
                {
                    "Keys": ["USE1-Input"],
                    "Metrics": {"UnblendedCost": {"Amount": "10.00", "Unit": "USD"}},
                }
            ],
        }
    ]
}


@pytest.fixture
def mock_auth():
    session = MagicMock()
    return AuthResult(account_id="123456789012", session=session)


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.region = "us-east-1"
    config.cache_ttl_hours = 24
    return config


class TestMCPRegistration:
    @pytest.mark.asyncio
    async def test_six_tools_registered(self):
        """Validates: Requirement 12.1"""
        tools = await mcp_server.list_tools()
        names = {tool.name for tool in tools}
        assert names == TOOL_NAMES


class TestToolInvocation:
    @pytest.mark.asyncio
    async def test_cost_summary_success(self, mock_auth, mock_config):
        with (
            patch("aws_cost_analytics.server.load_config", return_value=mock_config),
            patch(
                "aws_cost_analytics.server.AuthModule"
            ) as mock_auth_cls,
            patch("aws_cost_analytics.server.Executor") as mock_executor_cls,
        ):
            mock_auth_cls.return_value.get_credentials.return_value = mock_auth
            mock_executor_cls.return_value.get_cost_and_usage.return_value = (
                MOCK_CE_RESPONSE
            )

            result = await tool_get_cost_summary("2024-01-01", "2024-01-31")

        assert "Account 123456789012" in result
        assert "Total: $42.50 USD" in result
        assert not result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_cost_by_usage_type_success(self, mock_auth, mock_config):
        with (
            patch("aws_cost_analytics.server.load_config", return_value=mock_config),
            patch("aws_cost_analytics.server.AuthModule") as mock_auth_cls,
            patch("aws_cost_analytics.server.Executor") as mock_executor_cls,
        ):
            mock_auth_cls.return_value.get_credentials.return_value = mock_auth
            mock_executor_cls.return_value.get_cost_and_usage.return_value = (
                MOCK_GROUPED_RESPONSE
            )

            result = await tool_get_cost_by_usage_type("2024-01-01", "2024-01-31")

        assert "Usage Type" in result
        assert "USE1-Input" in result
        assert not result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_cost_by_region_success(self, mock_auth, mock_config):
        grouped = {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": "2024-01-01", "End": "2024-01-02"},
                    "Groups": [
                        {
                            "Keys": ["us-east-1"],
                            "Metrics": {
                                "UnblendedCost": {"Amount": "5.00", "Unit": "USD"}
                            },
                        }
                    ],
                }
            ]
        }
        with (
            patch("aws_cost_analytics.server.load_config", return_value=mock_config),
            patch("aws_cost_analytics.server.AuthModule") as mock_auth_cls,
            patch("aws_cost_analytics.server.Executor") as mock_executor_cls,
        ):
            mock_auth_cls.return_value.get_credentials.return_value = mock_auth
            mock_executor_cls.return_value.get_cost_and_usage.return_value = grouped

            result = await tool_get_cost_by_region("2024-01-01", "2024-01-31")

        assert "Region" in result
        assert "us-east-1" in result

    @pytest.mark.asyncio
    async def test_cost_trend_success(self, mock_auth, mock_config):
        with (
            patch("aws_cost_analytics.server.load_config", return_value=mock_config),
            patch("aws_cost_analytics.server.AuthModule") as mock_auth_cls,
            patch("aws_cost_analytics.server.Executor") as mock_executor_cls,
        ):
            mock_auth_cls.return_value.get_credentials.return_value = mock_auth
            mock_executor_cls.return_value.get_cost_and_usage.return_value = (
                MOCK_CE_RESPONSE
            )

            result = await tool_get_cost_trend(
                "2024-01-01", "2024-01-31", granularity="MONTHLY"
            )

        assert "Date" in result
        assert "2024-01-01" in result


class TestDefaultDates:
    @pytest.mark.asyncio
    async def test_default_date_range(self, mock_auth, mock_config):
        today = datetime.now(tz=timezone.utc).date()
        expected_start = today - timedelta(days=30)

        with (
            patch("aws_cost_analytics.server.load_config", return_value=mock_config),
            patch("aws_cost_analytics.server.AuthModule") as mock_auth_cls,
            patch("aws_cost_analytics.server.Executor") as mock_executor_cls,
        ):
            mock_auth_cls.return_value.get_credentials.return_value = mock_auth
            mock_executor_cls.return_value.get_cost_and_usage.return_value = (
                MOCK_CE_RESPONSE
            )

            await tool_get_cost_summary()

        call_args = mock_executor_cls.return_value.get_cost_and_usage.call_args[0]
        assert call_args[0] == expected_start
        assert call_args[1] == today


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_invalid_date_returns_error_string(self):
        result = await tool_get_cost_summary("2024-02-30", "2024-01-31")
        assert result.startswith("Error:")
        assert "Invalid start_time" in result
        assert "Traceback" not in result

    @pytest.mark.asyncio
    async def test_config_error_returns_error_string(self):
        with patch(
            "aws_cost_analytics.server.load_config",
            side_effect=ConfigError("bad config"),
        ):
            result = await tool_get_cost_summary("2024-01-01", "2024-01-31")
        assert result == "Error: bad config"

    @pytest.mark.asyncio
    async def test_auth_error_returns_error_string(self, mock_config):
        with (
            patch("aws_cost_analytics.server.load_config", return_value=mock_config),
            patch("aws_cost_analytics.server.AuthModule") as mock_auth_cls,
        ):
            mock_auth_cls.return_value.get_credentials.side_effect = AuthError(
                "no credentials"
            )
            result = await tool_get_cost_summary("2024-01-01", "2024-01-31")
        assert result == "Error: no credentials"

    @pytest.mark.asyncio
    async def test_executor_error_returns_error_string(self, mock_auth, mock_config):
        with (
            patch("aws_cost_analytics.server.load_config", return_value=mock_config),
            patch("aws_cost_analytics.server.AuthModule") as mock_auth_cls,
            patch("aws_cost_analytics.server.Executor") as mock_executor_cls,
        ):
            mock_auth_cls.return_value.get_credentials.return_value = mock_auth
            mock_executor_cls.return_value.get_cost_and_usage.side_effect = (
                ExecutorError("CE failed")
            )
            result = await tool_get_cost_summary("2024-01-01", "2024-01-31")
        assert result == "Error: CE failed"

    @pytest.mark.asyncio
    async def test_invalid_granularity_returns_error_string(self):
        result = await tool_get_cost_trend(
            "2024-01-01", "2024-01-31", granularity="WEEKLY"
        )
        assert result.startswith("Error:")
        assert "Invalid granularity" in result
