# API contract

Stable interface for CLI, MCP, and future TypeScript extension consumers.

Version: tracks `pyproject.toml` / [GitHub Releases](https://github.com/jajera/kiro-aws-cost-analytics/releases) (python-semantic-release on push to `main`).

## Entry points

| Command | Module | Purpose |
|---------|--------|---------|
| `aws-cost-analytics-cli` | `cli.py` | One-shot terminal queries |
| `aws-cost-analytics` | `server.py` | MCP stdio server |

Both call the same `tool_*` functions in `server.py`.

## Tools

| Tool | Default period | Notes |
|------|----------------|-------|
| `get-cost-summary` | Last 30 UTC days | Bedrock ecosystem net |
| `get-cost-by-usage-type` | Last 30 UTC days | Bedrock ecosystem net |
| `get-cost-by-region` | Last 30 UTC days | Bedrock ecosystem net |
| `get-cost-trend` | Last 30 UTC days | Bedrock ecosystem net; optional `granularity`, `group_by` |
| `get-kiro-cost-summary` | Full calendar month | Kiro subscription, credits, net |
| `reconcile-billing` | Full calendar month | Dashboard gross vs tool net |

### Shared parameters

- `start_time` — `YYYY-MM-DD` (optional)
- `end_time` — `YYYY-MM-DD` (optional)
- If both omitted, tool-specific default applies (see table above)
- `start_time` must not be after `end_time`

### `get-cost-trend` only

- `granularity` — `DAILY` (default) or `MONTHLY`
- `group_by` — `USAGE_TYPE`, `REGION`, or omitted

## Output

- Markdown text (tables + bullet summaries)
- Errors start with `Error:` (no stack traces to user)
- `reconcile-billing` sections:
  - Dashboard vs tool totals
  - Record type breakdown
  - Kiro subscription vs credits
  - Gross by service (dashboard bars)
  - Usage charges by service

## Credentials

Uses boto3 default chain (`AWS_PROFILE`, env vars, instance role). No credentials in repo config.

## Cache

- Directory: `~/.cache/aws-cost-analytics/`
- Bedrock discovery: `ce-services-bedrock.json`
- CE responses: `ce-{account}-{scope}-{tool}-{start}-{end}-{granularity}-{group}.json`
- Clear stale discovery: `rm ~/.cache/aws-cost-analytics/ce-services-bedrock.json`

## Constants

Public names live in `aws_cost_analytics.constants` (`TOOL_NAMES`, `MCP_SERVER_NAME`, etc.).

## Date helpers

`aws_cost_analytics.dates` — `today_utc()`, `calendar_month_period()`, `is_full_calendar_month()`.
