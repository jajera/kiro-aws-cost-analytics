# Review Monthly Spend

Guide Kiro through a structured monthly cost review using the aws-cost-analytics MCP tools.

## Tools Referenced

- `reconcile-billing`
- `get-kiro-cost-summary`
- `get-cost-summary`
- `get-cost-by-usage-type`
- `get-cost-by-region`
- `get-cost-trend`

## Workflow

### Step 1: Reconcile dashboard vs tools (calendar month)

Call `reconcile-billing` with no parameters (defaults to the **full current calendar month**).

From the response, note:

1. **Gross before credits** (matches Billing dashboard widget)
2. **Credits applied** and **net total**
3. **Gross by service** — which services dominate (e.g. Kiro subscription bar)
4. Whether dashboard-like gross differs sharply from net (credits/subscription offset)

### Step 2: Kiro subscription breakdown

Call `get-kiro-cost-summary` with no parameters (same calendar month).

Summarize:

1. Subscription gross and usage type (e.g. `USE1-KiroEnterprise-Pro`)
2. Kiro credits vs subscription
3. **Kiro net** — often $0 when credits fully offset subscription

### Step 3: Bedrock ecosystem net spend

Call `get-cost-summary` with `--days 30` (or explicit month range) for **Bedrock ecosystem net** spend.

Note total USD and date range. Flag if spend exceeds expected budget.

### Step 4: Top usage types

Call `get-cost-by-usage-type` for the same Bedrock period. Identify top 3 usage types and percentage of Bedrock total from Step 3.

### Step 5: Region skew

Call `get-cost-by-region` for the same period. Check concentration in one region vs distributed; flag unexpected regions.

### Step 6: Trend anomalies

Call `get-cost-trend` with `--days 30` and daily granularity. Scan for spikes, sustained trends, or zero-spend days.

## Expected Output

Produce a brief summary covering:

- Dashboard gross vs net (from reconcile)
- Kiro subscription vs credits
- Bedrock net total and top cost drivers
- Region distribution
- Notable trend anomalies or action items
