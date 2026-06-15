# Requirements Document

## Introduction

kiro-aws-cost-analytics is a read-only Bedrock and Kiro spend analysis tool that provides AWS Cost Explorer data through both a CLI and MCP server interface. It mirrors the architecture of kiro-aws-firewall-analytics, sharing the same patterns for authentication, guardrails, configuration, and tool exposure. Scope includes Cost Explorer queries for the Bedrock ecosystem, Kiro billing, and account-level billing reconciliation for a single target account, with formatted markdown output designed for low-token Kiro consumption.

## Glossary

- **Cost_Analytics_System**: The kiro-aws-cost-analytics application including CLI, MCP server, executors, formatter, and guardrails
- **Guardrail_Enforcer**: The module responsible for enforcing read-only API restrictions and account scope validation
- **Auth_Module**: The module responsible for resolving AWS credentials from the default boto3 credential chain and retrieving the active account identity
- **Config_Loader**: The module responsible for loading and validating config.json using pydantic
- **Executor**: The module responsible for calling Cost Explorer APIs and caching results
- **Formatter**: The module responsible for converting raw Cost Explorer responses into markdown tables with summary lines
- **MCP_Server**: The FastMCP-based server exposing tool functions to Kiro
- **CLI**: The command-line interface that calls the same tool functions as the MCP server
- **Cache**: Local file-based storage under `~/.cache/aws-cost-analytics/` for Cost Explorer results and Bedrock service discovery
- **Active_Account**: The AWS account (12-digit ID) resolved at runtime from the active AWS profile via STS GetCallerIdentity
- **Query_Date**: A calendar date in `YYYY-MM-DD` format used as an inclusive bound for user-facing date parameters
- **Today**: The current UTC calendar date, used for all default date calculations and cache freshness checks

## Date and Time Semantics

All tools share the following date rules:

1. User-facing `start_time` and `end_time` values are **inclusive** `Query_Date` bounds.
2. Cost Explorer `TimePeriod.Start` SHALL equal `start_time`.
3. Cost Explorer `TimePeriod.End` SHALL equal `end_time` plus one calendar day (Cost Explorer end dates are exclusive).
4. `Today` SHALL be computed in UTC.
5. Default date range (when `start_time` and/or `end_time` are omitted) SHALL be:
   - `start_time` = Today minus 30 days
   - `end_time` = Today
   This yields 31 inclusive calendar days of data.
6. The Formatter summary line SHALL display the inclusive user-facing range (`start_time` → `end_time`), not the exclusive API end date.

### Billing Tool Date Semantics

`get-kiro-cost-summary` and `reconcile-billing` use calendar-month defaults when `start_time` and `end_time` are both omitted:

1. `start_time` = first day of the calendar month containing Today (UTC)
2. `end_time` = last day of that calendar month
3. This aligns with the Billing console **Cost and usage** widget (full month, gross before credits for reconcile)
4. The CLI `--days` parameter SHALL be ignored for these two tools (no error; billing tools always use calendar month or explicit dates)

## Requirements

### Requirement 1: Configuration Loading and Validation

**User Story:** As a developer, I want minimal configuration with sensible defaults, so that the tool works with my existing AWS profile without redundant setup.

#### Acceptance Criteria

1. WHEN config.json is loaded, THE Config_Loader SHALL validate that region matches a valid AWS region format (lowercase letters, digits, and hyphens matching the pattern `[a-z]{2,4}-[a-z]+-\d{1,2}`)
2. WHEN region is not specified in config.json, THE Config_Loader SHALL default region to the boto3 session default region
3. IF region is not specified and the boto3 session has no default region, THEN THE Config_Loader SHALL default region to `us-east-1`
4. WHEN cache_ttl_hours is not specified in config.json, THE Config_Loader SHALL default cache_ttl_hours to 24
5. WHEN cache_ttl_hours is specified in config.json, THE Config_Loader SHALL validate that the value is an integer between 1 and 168 inclusive
6. IF config.json is missing, THEN THE Config_Loader SHALL operate with all default values
7. IF config.json contains an unrecognized field name (not `region` or `cache_ttl_hours`), THEN THE Config_Loader SHALL return a descriptive error identifying the unrecognized field
8. IF config.json contains a recognized field with an invalid value, THEN THE Config_Loader SHALL return a descriptive error identifying the field and the validation constraint that failed
9. IF config.json contains malformed JSON (syntax error), THEN THE Config_Loader SHALL return a descriptive error indicating the file could not be parsed

### Requirement 2: Authentication and Account Resolution

**User Story:** As a developer, I want the tool to use my active AWS profile credentials automatically, so that I do not need to duplicate authentication configuration.

#### Acceptance Criteria

1. WHEN a tool function is invoked, THE Auth_Module SHALL resolve credentials using the default boto3 credential chain (AWS_PROFILE, environment variables, instance roles)
2. WHEN credentials are resolved, THE Auth_Module SHALL call sts:GetCallerIdentity to obtain the active 12-digit account ID
3. WHEN authentication succeeds, THE Auth_Module SHALL return both the active account ID and a boto3 Session to the calling tool function
4. THE Auth_Module SHALL return a boto3 Session scoped to the region resolved by the Config_Loader
5. IF credentials cannot be resolved or the sts:GetCallerIdentity call fails, THEN THE Auth_Module SHALL return an error indicating whether the failure was due to credential resolution or STS call failure
6. IF the sts:GetCallerIdentity call does not receive a response within 10 seconds, THEN THE Auth_Module SHALL treat the call as failed and return an error indicating a timeout

### Requirement 3: Read-Only Guardrails

**User Story:** As a developer, I want hard-coded read-only guardrails that restrict API calls to an explicit allowlist, so that the tool cannot perform writes or access unintended services.

#### Acceptance Criteria

1. THE Guardrail_Enforcer SHALL maintain an explicit allowlist of permitted Cost Explorer actions: GetCostAndUsage, GetDimensionValues
2. IF a requested API action is not in the explicit allowlist, THEN THE Guardrail_Enforcer SHALL reject the request with an error identifying the blocked action
3. THE Guardrail_Enforcer SHALL enforce the allowlist using exact case-sensitive action name matching, not prefix matching
4. THE Guardrail_Enforcer SHALL enforce a Bedrock ecosystem service filter on all Bedrock cost queries by discovering SERVICE dimension values via GetDimensionValues with SearchString `Bedrock`, caching the result locally, and applying an OR filter across all discovered services
5. THE Guardrail_Enforcer SHALL provide a separate Kiro scope that filters only SERVICE = `Kiro` for the get-kiro-cost-summary tool
6. IF a query attempts to use SERVICE values outside the discovered Bedrock ecosystem set or outside the Kiro allowlist, THEN THE Guardrail_Enforcer SHALL reject the request with an error identifying the filter violation
7. THE Guardrail_Enforcer SHALL be invoked on every outbound Cost Explorer API call before the call is executed

### Requirement 4: Input Validation

**User Story:** As a developer, I want invalid inputs rejected with clear errors, so that tool behavior is predictable and safe.

#### Acceptance Criteria

1. WHEN a tool receives `start_time` or `end_time`, THE Cost_Analytics_System SHALL validate that each value is a valid calendar date in `YYYY-MM-DD` format (rejecting non-existent dates such as `2024-02-30`)
2. IF `start_time` is after `end_time`, THEN THE Cost_Analytics_System SHALL reject the request with an error message indicating that `start_time` must not be later than `end_time`
3. IF both `--days` and either `--start-time` or `--end-time` are provided on the CLI, THEN THE CLI SHALL reject the request with an error message indicating that `--days` cannot be combined with explicit date parameters
4. WHEN get-cost-trend receives a `granularity` value, THE Cost_Analytics_System SHALL accept only the case-sensitive values `DAILY` or `MONTHLY`
5. IF get-cost-trend receives an unsupported `granularity`, THEN THE Cost_Analytics_System SHALL reject the request with an error message indicating the invalid value and the accepted values (`DAILY`, `MONTHLY`)
6. WHEN get-cost-trend receives a `group_by` value, THE Cost_Analytics_System SHALL accept only the case-sensitive values `USAGE_TYPE`, `REGION`, or no group-by (omitted/`null`)
7. IF get-cost-trend receives an unsupported `group_by`, THEN THE Cost_Analytics_System SHALL reject the request with an error message indicating the invalid value and the accepted values (`USAGE_TYPE`, `REGION`)
8. IF `--days` is provided on the CLI, THEN THE CLI SHALL validate that the value is an integer between 1 and 365 inclusive
9. IF `--days` is provided with a value less than 1 or greater than 365, THEN THE CLI SHALL reject the request with an error message indicating the accepted range (1 to 365)

### Requirement 5: Cost Summary Tool

**User Story:** As a developer, I want to retrieve total Bedrock spend for a given period, so that I can quickly understand overall cost.

#### Acceptance Criteria

1. WHEN get-cost-summary is invoked without `start_time`, THE Cost_Analytics_System SHALL default `start_time` per Date and Time Semantics
2. WHEN get-cost-summary is invoked without `end_time`, THE Cost_Analytics_System SHALL default `end_time` per Date and Time Semantics
3. WHEN get-cost-summary is invoked, THE Executor SHALL call GetCostAndUsage with metric UnblendedCost and no GroupBy dimension
4. WHEN get-cost-summary is invoked, THE Executor SHALL map the date range to Cost Explorer per Date and Time Semantics
5. WHEN get-cost-summary is invoked, THE Executor SHALL include the Bedrock ecosystem service filter (discovered SERVICE values matching Bedrock, combined with OR)
6. WHEN results are returned, THE Formatter SHALL sum the Amount values across all ResultsByTime entries, round to 2 decimal places, and produce a summary line containing the account ID, inclusive date range, and total USD amount
7. IF the Cost Explorer API call fails or times out, THEN THE Cost_Analytics_System SHALL return a descriptive error indicating the failure reason without exposing raw exception details

### Requirement 6: Cost by Usage Type Tool

**User Story:** As a developer, I want to see Bedrock spend broken down by usage type, so that I can identify top cost drivers such as token consumption and model invocations.

#### Acceptance Criteria

1. WHEN get-cost-by-usage-type is invoked without `start_time` or `end_time`, THE Cost_Analytics_System SHALL apply default dates per Date and Time Semantics
2. WHEN get-cost-by-usage-type is invoked, THE Executor SHALL call GetCostAndUsage with metric UnblendedCost and GroupBy dimension USAGE_TYPE (Type=DIMENSION, Key=USAGE_TYPE)
3. WHEN get-cost-by-usage-type is invoked, THE Executor SHALL map the date range to Cost Explorer per Date and Time Semantics
4. WHEN get-cost-by-usage-type is invoked, THE Executor SHALL include the Bedrock ecosystem service filter
5. WHEN results are returned, THE Formatter SHALL produce a markdown table with columns: usage type, amount (USD to 2 decimal places), with rows sorted by amount descending so that top cost drivers appear first
6. WHEN results are returned, THE Formatter SHALL aggregate costs across the entire queried date range (one row per usage type, not per day)
7. IF all usage type groups return a total amount of zero, THEN THE Formatter SHALL produce a message indicating no cost data was found for the period

### Requirement 7: Cost by Region Tool

**User Story:** As a developer, I want to see Bedrock spend broken down by region, so that I can identify regional cost distribution.

#### Acceptance Criteria

1. WHEN get-cost-by-region is invoked without `start_time` or `end_time`, THE Cost_Analytics_System SHALL apply default dates per Date and Time Semantics
2. WHEN get-cost-by-region is invoked, THE Executor SHALL call GetCostAndUsage with metric UnblendedCost and GroupBy dimension REGION (Type=DIMENSION, Key=REGION)
3. WHEN get-cost-by-region is invoked, THE Executor SHALL map the date range to Cost Explorer per Date and Time Semantics
4. WHEN get-cost-by-region is invoked, THE Executor SHALL include the Bedrock ecosystem service filter
5. WHEN results are returned, THE Formatter SHALL produce a markdown table with columns: region, amount (USD to 2 decimal places), with rows sorted by amount descending
6. WHEN results are returned, THE Formatter SHALL aggregate costs across the entire queried date range (one row per region, not per day)
7. IF all region groups return a total amount of zero, THEN THE Formatter SHALL produce a message indicating no cost data was found for the period

### Requirement 8: Cost Trend Tool

**User Story:** As a developer, I want to see Bedrock spend as a daily or monthly time series, so that I can identify cost trends and spikes.

#### Acceptance Criteria

1. WHEN get-cost-trend is invoked without `start_time` or `end_time`, THE Cost_Analytics_System SHALL apply default dates per Date and Time Semantics
2. WHEN get-cost-trend is invoked without `granularity`, THE Cost_Analytics_System SHALL default `granularity` to `DAILY`
3. WHEN get-cost-trend is invoked, THE Executor SHALL call GetCostAndUsage with metric UnblendedCost and the specified `granularity` (`DAILY` or `MONTHLY`)
4. WHEN get-cost-trend is invoked with an optional `group_by`, THE Executor SHALL include the specified GroupBy dimension (`USAGE_TYPE` or `REGION`)
5. WHEN get-cost-trend is invoked without `group_by`, THE Executor SHALL call GetCostAndUsage with no GroupBy dimension
6. WHEN get-cost-trend is invoked, THE Executor SHALL map the date range to Cost Explorer per Date and Time Semantics
7. WHEN get-cost-trend is invoked, THE Executor SHALL include the Bedrock ecosystem service filter
8. WHEN results are returned without `group_by`, THE Formatter SHALL produce a markdown table with columns: date and amount
9. WHEN results are returned with `group_by`, THE Formatter SHALL produce a markdown table with columns: date, the group dimension value, and amount

### Requirement 9: Output Formatting and Truncation

**User Story:** As a developer, I want formatted markdown output with controlled row counts, so that Kiro token consumption stays low and results are readable.

#### Acceptance Criteria

1. THE Formatter SHALL produce a summary line before the table in the format: "Account {active_account_id} | {start_date} → {end_date} | Total: ${amount} USD" where amount is formatted to 2 decimal places
2. THE Formatter SHALL format cost data as a pipe-delimited markdown table with a header row and separator row
3. WHEN result data rows exceed 50, THE Formatter SHALL truncate output to the first 50 data rows in the order returned by the Cost Explorer response
4. WHEN output is truncated, THE Formatter SHALL append a footer message: "Narrow date range or use a specific group-by"
5. WHEN results contain zero rows, THE Formatter SHALL produce a message indicating no cost data was found for the period
6. THE Formatter SHALL format all USD amount values in the table to 2 decimal places

### Requirement 10: Result Caching

**User Story:** As a developer, I want Cost Explorer results cached locally, so that repeated queries do not make unnecessary API calls.

#### Acceptance Criteria

1. THE Executor SHALL derive a cache key from all query-shaping parameters: `active_account_id`, tool name, `start_time`, `end_time`, `granularity` (or `none`), and `group_by` (or `none`)
2. WHEN the Executor receives Cost Explorer results and the query `end_time` does not equal Today (UTC), THE Executor SHALL write the raw Cost Explorer JSON response to `~/.cache/aws-cost-analytics/ce-{active_account_id}-{scope}-{tool}-{start}-{end}-{granularity}-{group_by}.json`
3. WHEN a cached result exists for the same cache key and the file modification time is less than `cache_ttl_hours` (default 24) hours before the current UTC time, THE Executor SHALL return the cached result without calling Cost Explorer
4. IF the query `end_time` equals Today (UTC), THEN THE Executor SHALL skip both cache lookup and cache write, and always call Cost Explorer
5. THE Executor SHALL create `~/.cache/aws-cost-analytics/` if it does not exist
6. IF a cache file exists but cannot be read or contains invalid JSON, THEN THE Executor SHALL treat the request as a cache miss and call Cost Explorer

### Requirement 11: CLI Interface

**User Story:** As a developer, I want a CLI with the same subcommands as the MCP tools, so that I can query costs directly from the terminal.

#### Acceptance Criteria

1. THE CLI SHALL expose subcommands: get-cost-summary, get-cost-by-usage-type, get-cost-by-region, get-cost-trend, get-kiro-cost-summary, reconcile-billing
2. THE CLI SHALL accept `--start-time` and `--end-time` parameters on all subcommands
3. THE CLI SHALL accept a `--days` parameter as a positive integer between 1 and 365 (inclusive) on Bedrock subcommands as a shorthand for `start_time = Today minus N days` and `end_time = Today` (per Date and Time Semantics)
4. IF `--days` is provided together with `--start-time` or `--end-time`, THEN THE CLI SHALL reject the request with an error message indicating that `--days` cannot be combined with explicit date parameters
5. IF `--days` is provided with a value less than 1 or greater than 365, THEN THE CLI SHALL reject the request with an error message indicating the valid range
6. THE get-cost-trend subcommand SHALL accept `--granularity` (`DAILY` or `MONTHLY`) and optional `--group-by` (`USAGE_TYPE` or `REGION`)
7. THE CLI SHALL call the same `tool_*` functions in `server.py` that the MCP server uses
8. WHEN the same parameters are provided, THE CLI SHALL print to stdout the formatted markdown string identical to the MCP server response
9. WHEN a subcommand completes successfully, THE CLI SHALL exit with code 0
10. IF a subcommand fails due to invalid input or an execution error, THEN THE CLI SHALL print an error message to stderr and exit with a non-zero exit code

### Requirement 12: MCP Server Interface

**User Story:** As a developer, I want an MCP server exposing the cost analysis tools, so that Kiro can invoke them directly during investigation.

#### Acceptance Criteria

1. THE MCP_Server SHALL expose six tools: get-cost-summary, get-cost-by-usage-type, get-cost-by-region, get-cost-trend, get-kiro-cost-summary, and reconcile-billing
2. THE MCP_Server SHALL use FastMCP from mcp.server.fastmcp
3. THE MCP_Server SHALL import `tool_*` functions from the server module and register them as MCP tools using the `@mcp_server.tool()` decorator
4. WHEN a tool is invoked via MCP, THE MCP_Server SHALL return the result as a text content block containing formatted markdown, not raw Cost Explorer JSON
5. THE MCP_Server SHALL use stdio transport mode
6. IF a tool function raises an exception during MCP invocation, THEN THE MCP_Server SHALL return an MCP error response containing an error message indicating the failure reason

### Requirement 13: Shared Tool Functions

**User Story:** As a developer, I want a single set of tool functions shared between CLI and MCP, so that query logic is not duplicated.

#### Acceptance Criteria

1. THE Cost_Analytics_System SHALL implement tool functions (`tool_get_cost_summary`, `tool_get_cost_by_usage_type`, `tool_get_cost_by_region`, `tool_get_cost_trend`, `tool_get_kiro_cost_summary`, `tool_reconcile_billing`) in `server.py`, where each function orchestrates config loading, authentication, guardrail enforcement, executor invocation, and formatter or reconciliation output, and returns a formatted markdown string
2. THE CLI SHALL import and call the tool functions from `server.py` without wrapping or duplicating the orchestration logic contained within them
3. THE MCP_Server SHALL import and call the tool functions from `server.py` without wrapping or duplicating the orchestration logic contained within them
4. THE Cost_Analytics_System SHALL contain no query orchestration logic (config loading, authentication, guardrail enforcement, Cost Explorer API calls, or result formatting) outside of the shared tool functions in `server.py`
5. WHEN the CLI and MCP_Server invoke the same tool function with identical parameters, THE Cost_Analytics_System SHALL produce identical formatted markdown output from both interfaces

### Requirement 14: Steering Playbooks

**User Story:** As a developer, I want steering playbooks that guide Kiro through common cost investigation workflows, so that analysis is structured and repeatable.

#### Acceptance Criteria

1. THE Cost_Analytics_System SHALL include a `review-monthly-spend.md` steering playbook located in `.kiro/steering/` that references tool names `reconcile-billing`, `get-kiro-cost-summary`, `get-cost-summary`, `get-cost-by-usage-type`, `get-cost-by-region`, and `get-cost-trend`, and prescribes workflow steps covering: reconciling dashboard gross vs net for the calendar month, summarizing Kiro subscription vs credits, summarizing Bedrock net spend, identifying top usage types, and checking region skew
2. THE Cost_Analytics_System SHALL include an `investigate-spike.md` steering playbook located in `.kiro/steering/` that references tool names `reconcile-billing`, `get-cost-trend`, `get-cost-by-usage-type`, and `get-cost-by-region`, and prescribes workflow steps covering: ruling out subscription/credit effects via reconcile, retrieving daily trend for the last 14 days, identifying spike dates, narrowing by usage-type and region, and hypothesizing the cause
3. THE steering playbooks SHALL reference MCP tool names using the exact names exposed by the MCP_Server (`get-cost-summary`, `get-cost-by-usage-type`, `get-cost-by-region`, `get-cost-trend`, `get-kiro-cost-summary`, `reconcile-billing`), not AWS CLI command syntax

### Requirement 15: Kiro Cost Summary Tool

**User Story:** As a developer, I want to retrieve Kiro IDE spend separately from Bedrock inference, so that I can track Kiro subscription costs without mixing them with model usage.

#### Acceptance Criteria

1. WHEN get-kiro-cost-summary is invoked without `start_time` and `end_time`, THE Cost_Analytics_System SHALL apply Billing Tool Date Semantics (full calendar month)
2. WHEN get-kiro-cost-summary is invoked, THE reconciliation module SHALL query GetCostAndUsage grouped by RECORD_TYPE with filter SERVICE = `Kiro`
3. WHEN get-kiro-cost-summary is invoked, THE Cost_Analytics_System SHALL return subscription gross, credits, usage, net total, and subscription usage type when present
4. THE get-kiro-cost-summary tool SHALL be exposed via both the MCP_Server and the CLI

### Requirement 16: Billing Reconciliation Tool

**User Story:** As a developer, I want to reconcile Billing dashboard gross spend with net tool totals, so that I can explain discrepancies such as Kiro subscription vs credits.

#### Acceptance Criteria

1. WHEN reconcile-billing is invoked without `start_time` and `end_time`, THE Cost_Analytics_System SHALL apply Billing Tool Date Semantics (full calendar month)
2. WHEN reconcile-billing is invoked, THE reconciliation module SHALL query account-level totals grouped by RECORD_TYPE and compute gross before credits, credits applied, and net total
3. WHEN reconcile-billing is invoked, THE reconciliation module SHALL return Kiro subscription, credits, usage, and net; gross-by-service breakdown (dashboard bar chart); and usage-by-service breakdown
4. WHEN reconcile-billing is invoked, THE Cost_Analytics_System SHALL include Bedrock ecosystem net total for comparison
5. THE reconcile-billing tool SHALL be exposed via both the MCP_Server and the CLI
