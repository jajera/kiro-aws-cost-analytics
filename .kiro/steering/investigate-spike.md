# Investigate Cost Spike

Guide Kiro through a structured investigation of unexpected spend using the aws-cost-analytics MCP tools.

## Tools Referenced

- `reconcile-billing`
- `get-cost-trend`
- `get-cost-by-usage-type`
- `get-cost-by-region`

## Workflow

### Step 0: Rule out billing vs usage (calendar month)

Call `reconcile-billing` with no parameters.

Check whether the apparent "spike" is:

1. **Gross subscription** (e.g. Kiro flat-rate) with offsetting credits
2. A real **usage** increase in the Usage record type
3. A **calendar-month** effect (partial month vs full month)

If gross is high but net is near zero, the spike may be a dashboard display artifact (pre-credit), not runaway usage.

### Step 1: Retrieve daily Bedrock trend (last 14 days)

Call `get-cost-trend` with `--days 14` and daily granularity for **Bedrock ecosystem net** spend.

### Step 2: Identify spike dates

Review the daily trend for:

1. Single-day spikes
2. Multi-day sustained increases
3. Magnitude vs baseline

### Step 3: Narrow by usage type

Call `get-cost-by-usage-type` with `start_time` and `end_time` set to spike date(s). Identify which usage types drove the increase.

### Step 4: Narrow by region

Call `get-cost-by-region` for the spike date(s). Identify region(s) involved.

### Step 5: Hypothesize cause

Common causes:

1. Increased workload / token volume
2. Model switch to a more expensive edition
3. New deployment or feature using Bedrock
4. Batch or one-off processing
5. Region misconfiguration

## Expected Output

- Whether reconcile explains gross vs net
- Spike date(s) and magnitude (Bedrock net)
- Primary usage types and regions
- Hypothesized root cause
- Recommended next steps
