# Implementation Plan: AWS Cost Analytics

## Overview

Build a read-only AWS Cost Explorer analysis tool for Amazon Bedrock spend, exposed via FastMCP server and CLI. The implementation follows a scaffold-first approach: project structure → guardrails → executors → formatter → server wiring → CLI → documentation → steering playbooks → MCP config.

## Tasks

- [x] 1. Scaffold project structure and core interfaces
  - [x] 1.1 Create pyproject.toml with hatchling build system
    - Define `[build-system]` with hatchling
    - Set package metadata: name=aws-cost-analytics, version, description, Python >=3.11
    - Add dependencies: boto3>=1.34.0, mcp>=1.0.0, pydantic>=2.0.0
    - Add dev dependencies: pytest>=7.4.0, pytest-asyncio>=0.21.0, hypothesis>=6.82.0, moto>=4.2.0
    - Define entry point: `aws-cost-analytics = "aws_cost_analytics.server:main"`
    - _Requirements: 12.2, 11.1_

  - [x] 1.2 Create package layout and module stubs
    - Create `src/aws_cost_analytics/__init__.py`
    - Create stubs for: `config.py`, `auth.py`, `guardrails.py`, `executors.py`, `formatter.py`, `server.py`, `cli.py`
    - Create `tests/` directory with `__init__.py` and `conftest.py`
    - _Requirements: 13.1_

  - [x] 1.3 Implement config.py with pydantic validation
    - Define `Config` pydantic model with `region` (str, default "") and `cache_ttl_hours` (int, default 24)
    - Add `field_validator` for region pattern: `[a-z]{2,4}-[a-z]+-\d{1,2}` (accept empty string as "use default")
    - Add `field_validator` for cache_ttl_hours: 1–168 inclusive
    - Set `model_config` with `extra = "forbid"` to reject unrecognized fields
    - Implement `load_config(path)` that returns defaults if file missing, raises `ConfigError` on parse/validation failure
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9_

  - [x] 1.4 Implement auth.py with boto3 credential chain
    - Define `AuthResult` dataclass with `account_id` (str) and `session` (boto3.Session)
    - Define `AuthError` exception class
    - Implement `AuthModule.__init__(region)` and `get_credentials()` method
    - Use botocore config with connect_timeout=5, read_timeout=5 for STS call
    - Resolve region: if empty, use session.region_name; if None, fall back to "us-east-1"
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [x] 2. Implement guardrails with property tests
  - [x] 2.1 Implement guardrails.py
    - Define `ALLOWED_ACTIONS` as `frozenset({"GetCostAndUsage", "GetDimensionValues"})`
    - Define `REQUIRED_SERVICE_FILTER` dict with Key=SERVICE, Values=["Amazon Bedrock"]
    - Define `GuardrailError` exception class
    - Implement `GuardrailEnforcer.validate(action, filters)` with exact-match action check and Bedrock filter presence check
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 2.2 Write property tests for config validation
    - **Property 1: Region validation accepts only valid AWS region patterns**
    - **Property 2: Cache TTL range validation**
    - **Property 3: Unrecognized config fields are rejected**
    - **Validates: Requirements 1.1, 1.5, 1.7**

  - [x] 2.3 Write property tests for guardrail enforcement
    - **Property 4: Guardrail action allowlist is exact-match only**
    - **Property 5: Guardrail requires Amazon Bedrock service filter**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

  - [x] 2.4 Write unit tests for config and auth modules
    - Test config loading with missing file (defaults), valid config, invalid region, invalid TTL, unrecognized fields, malformed JSON
    - Test auth module with mocked STS (success, timeout, credential failure)
    - _Requirements: 1.1–1.9, 2.1–2.6_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement executors with caching
  - [x] 4.1 Implement executors.py with fetch_bedrock_cost helper
    - Define `ExecutorError` exception class
    - Implement `Executor.__init__(session, account_id, cache_ttl_hours)` — creates CE client, sets cache_dir to `~/.cache/aws-cost-analytics/`
    - Implement `_cache_key(tool, start, end, granularity, group_by)` — returns filename `ce-{account}-{tool}-{start}-{end}-{gran}-{group}.json`
    - Implement `_is_cache_fresh(path)` — check mtime against TTL
    - Implement `get_cost_and_usage(start_time, end_time, granularity, group_by)`:
      - Derive cache key
      - If end_time != today(UTC): check cache, return if fresh
      - Call CE GetCostAndUsage with TimePeriod (end+1 day exclusive), Metrics=["UnblendedCost"], Filter=SERVICE/Amazon Bedrock, optional GroupBy
      - If end_time != today(UTC): write result to cache (mkdir parents)
      - Handle invalid cache files as cache miss
    - _Requirements: 5.3, 5.4, 5.5, 6.2, 6.3, 6.4, 7.2, 7.3, 7.4, 8.3, 8.4, 8.5, 8.6, 8.7, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 4.2 Write property tests for executor
    - **Property 10: Date-range to Cost Explorer mapping**
    - **Property 14: Cache key uniqueness**
    - **Validates: Requirements 5.4, 6.3, 7.3, 8.6, 10.1**

  - [x] 4.3 Write unit tests for executor caching behavior
    - Test cache hit (fresh file, returns without API call)
    - Test cache miss (expired file, calls API)
    - Test cache bypass when end_time == today
    - Test cache write on successful query
    - Test corrupted cache file treated as miss
    - Test cache directory auto-creation
    - _Requirements: 10.1–10.6_

- [x] 5. Implement formatter with truncation
  - [x] 5.1 Implement formatter.py
    - Define `MAX_ROWS = 50` and `TRUNCATION_FOOTER` constant
    - Implement `Formatter.format_summary(account_id, start, end, results)` — sum amounts, round to 2dp, produce summary line
    - Implement `Formatter.format_table(account_id, start, end, results, columns, group_key)` — summary + markdown table, aggregate by group, sort desc, truncate at 50 rows
    - Implement `Formatter.format_trend(account_id, start, end, results, group_key)` — summary + chronological table, optional group column, truncate at 50 rows
    - Handle zero-result case with descriptive message
    - _Requirements: 5.6, 6.5, 6.6, 6.7, 7.5, 7.6, 7.7, 8.8, 8.9, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x] 5.2 Write property tests for formatter
    - **Property 11: Summary computation sums and rounds correctly**
    - **Property 12: Grouped table aggregation and sort order**
    - **Property 13: Truncation at 50 rows with footer**
    - **Validates: Requirements 5.6, 6.5, 6.6, 7.5, 7.6, 9.1, 9.3, 9.4**

  - [x] 5.3 Write unit tests for formatter edge cases
    - Test zero-result output message
    - Test exactly 50 rows (no truncation)
    - Test 51 rows (truncation with footer)
    - Test amount rounding (2dp)
    - Test summary line format matches spec
    - _Requirements: 9.1–9.6_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement server.py with MCP registration and tool functions
  - [x] 7.1 Implement shared tool functions and input validation
    - Implement input validation helpers: `_validate_dates(start_time, end_time)` (parse YYYY-MM-DD, check ordering), `_validate_granularity(value)`, `_validate_group_by(value)`
    - Implement default date logic: if omitted, start_time = today-30, end_time = today (UTC)
    - Implement `tool_get_cost_summary(start_time, end_time)` — orchestrates config → auth → validate → guardrail → executor → formatter.format_summary
    - Implement `tool_get_cost_by_usage_type(start_time, end_time)` — same flow with GroupBy=USAGE_TYPE, formatter.format_table
    - Implement `tool_get_cost_by_region(start_time, end_time)` — same flow with GroupBy=REGION, formatter.format_table
    - Implement `tool_get_cost_trend(start_time, end_time, granularity, group_by)` — same flow with formatter.format_trend
    - Each tool catches module exceptions and returns user-friendly error strings
    - _Requirements: 4.1, 4.2, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.7, 6.1, 7.1, 8.1, 8.2, 13.1, 13.4_

  - [x] 7.2 Register tools with FastMCP and define main()
    - Create `mcp_server = FastMCP("aws-cost-analytics")`
    - Decorate each tool function with `@mcp_server.tool()`
    - Define `main()` that calls `mcp_server.run(transport="stdio")`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [x] 7.3 Write property tests for input validation
    - **Property 6: Date validation accepts only real calendar dates**
    - **Property 7: Start-time must not be after end-time**
    - **Property 8: Granularity and group_by enum validation**
    - **Validates: Requirements 4.1, 4.2, 4.4, 4.5, 4.6, 4.7**

  - [x] 7.4 Write unit tests for server integration
    - Test MCP tool registration (6 tools registered with correct names)
    - Test tool invocation with mocked executor (end-to-end with moto)
    - Test error handling returns user-friendly messages (no tracebacks)
    - Test default date calculation (today-30 to today)
    - _Requirements: 12.1, 12.4, 12.6, 13.5_

- [x] 8. Implement cli.py
  - [x] 8.1 Implement CLI with argparse and asyncio.run()
    - Create argparse with subcommands: get-cost-summary, get-cost-by-usage-type, get-cost-by-region, get-cost-trend, get-kiro-cost-summary, reconcile-billing
    - Add shared arguments: `--start-time`, `--end-time`, `--days` (int, 1–365)
    - Add get-cost-trend specific: `--granularity` (DAILY/MONTHLY), `--group-by` (USAGE_TYPE/REGION)
    - Validate `--days` mutual exclusivity with `--start-time`/`--end-time`
    - Validate `--days` range (1–365)
    - Convert `--days` to start_time/end_time (today - N days, today)
    - Call appropriate `tool_*` function via `asyncio.run()`
    - Print result to stdout on success (exit 0), errors to stderr (exit non-zero)
    - _Requirements: 4.3, 4.8, 4.9, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 11.10, 13.2_

  - [x] 8.2 Write property test for --days validation
    - **Property 9: Days parameter range validation**
    - **Validates: Requirements 4.8, 4.9**

  - [x] 8.3 Write unit tests for CLI argument parsing
    - Test subcommand registration (6 subcommands)
    - Test --days mutual exclusivity with --start-time/--end-time
    - Test --days range validation (0 rejected, 366 rejected, 1 and 365 accepted)
    - Test --granularity and --group-by on get-cost-trend only
    - Test exit codes (0 on success, non-zero on error)
    - _Requirements: 11.1–11.10_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Create config.json.example and README
  - [x] 10.1 Create config.json.example
    - Provide example JSON with `region` and `cache_ttl_hours` fields
    - Add comments (as separate markdown doc or inline notes) explaining defaults
    - _Requirements: 1.1, 1.4, 1.5_

  - [x] 10.2 Write README.md mirroring firewall Quick Start format
    - Include: overview, prerequisites (AWS credentials, Python 3.11+), installation (pip install -e . / uvx from GitHub), configuration (config.json), CLI usage examples (all 6 subcommands), MCP setup reference, architecture diagram, development setup (pytest)
    - _Requirements: 11.1, 12.1_

- [x] 11. Create steering playbooks *(updated for v0.2.0 — reconcile-billing, calendar month)*
  - [x] 11.1 review-monthly-spend.md — reconcile first, then Bedrock drill-down
  - [x] 11.2 investigate-spike.md — reconcile to rule out gross/credit effects

- [x] 12. User-local MCP config *(see `mcp.json.example`; not committed)*
  - [ ] 12.1 Merge `mcp.json.example` into Cursor/Kiro settings (`uvx` + GitHub URL)

- [x] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. v0.2.0 — reconciliation, cache, public install docs
  - [x] 14.1 Implement reconciliation.py and reconcile-billing / enhanced get-kiro-cost-summary
  - [x] 14.2 Move cache to ~/.cache/aws-cost-analytics/ (paths.py)
  - [x] 14.3 Add constants.py, dates.py, api-contract, mcp.json.example, release workflow
  - [x] 14.4 Update requirements, design, steering for six tools and calendar month
  - [x] 14.5 Remove scripts/reconcile_costs.py

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (14 properties total)
- Unit tests validate specific examples and edge cases
- The build order follows the user's preferred scaffold-first approach, mirroring kiro-aws-firewall-analytics patterns
- Python is the implementation language (specified in design)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "1.4"] },
    { "id": 3, "tasks": ["2.1", "2.4"] },
    { "id": 4, "tasks": ["2.2", "2.3"] },
    { "id": 5, "tasks": ["4.1"] },
    { "id": 6, "tasks": ["4.2", "4.3", "5.1"] },
    { "id": 7, "tasks": ["5.2", "5.3"] },
    { "id": 8, "tasks": ["7.1"] },
    { "id": 9, "tasks": ["7.2", "7.3"] },
    { "id": 10, "tasks": ["7.4", "8.1"] },
    { "id": 11, "tasks": ["8.2", "8.3"] },
    { "id": 12, "tasks": ["10.1", "10.2", "11.1", "11.2", "12.1"] }
  ]
}
```
