"""Tests for public package constants."""

from aws_cost_analytics import MCP_SERVER_NAME, TOOL_NAMES, __version__
from aws_cost_analytics.constants import BILLING_TOOL_NAMES, BEDROCK_TOOL_NAMES


def test_version():
    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_tool_names_partition():
    assert BEDROCK_TOOL_NAMES | BILLING_TOOL_NAMES == TOOL_NAMES
    assert len(TOOL_NAMES) == 6


def test_mcp_server_name():
    assert MCP_SERVER_NAME == "aws-cost-analytics"
