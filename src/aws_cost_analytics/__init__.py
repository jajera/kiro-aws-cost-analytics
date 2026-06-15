"""AWS Cost Analytics - Read-only Cost Explorer analysis for Bedrock and Kiro spend.

Provides a CLI (`aws-cost-analytics-cli`), MCP server (`aws-cost-analytics`),
and shared tool functions for querying AWS Cost Explorer.
"""

from aws_cost_analytics.constants import MCP_SERVER_NAME, TOOL_NAMES

__version__ = "0.1.0"
__all__ = ["MCP_SERVER_NAME", "TOOL_NAMES", "__version__"]
