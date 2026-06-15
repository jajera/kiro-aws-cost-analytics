"""Cost Explorer execution and result caching.

Calls AWS Cost Explorer APIs with Bedrock ecosystem or Kiro SERVICE
filters. Results are cached under ~/.cache/aws-cost-analytics/ with configurable TTL.
Cache is bypassed when end_time equals today (UTC) to ensure current-day
data is always live.
"""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from aws_cost_analytics.paths import default_cache_dir


class ExecutorError(Exception):
    """Raised when a Cost Explorer API call fails or times out."""

    pass


class Executor:
    """Executes Cost Explorer queries with local file caching."""

    def __init__(
        self,
        session,
        account_id: str,
        cache_ttl_hours: int,
        cache_dir: Path | None = None,
    ):
        """Initialize the executor.

        Args:
            session: A boto3 Session used to create the CE client.
            account_id: The 12-digit AWS account ID for cache key derivation.
            cache_ttl_hours: Number of hours before cached results are stale.
            cache_dir: Cache directory (default ~/.cache/aws-cost-analytics).
        """
        self._ce_client = session.client("ce")
        self._account_id = account_id
        self._cache_ttl_hours = cache_ttl_hours
        self._cache_dir = cache_dir or default_cache_dir()

    def _cache_key(
        self,
        tool: str,
        start: date,
        end: date,
        gran: str,
        group: str,
        scope: str,
    ) -> str:
        """Generate a cache filename from query-shaping parameters.

        Args:
            tool: Tool name segment (e.g., "cost-summary", "cost-trend").
            start: Inclusive start date.
            end: Inclusive end date.
            gran: Granularity string (DAILY, MONTHLY, or "none").
            group: Group-by dimension (USAGE_TYPE, REGION, or "none").
            scope: Service scope segment (e.g. bedrock-{hash}, kiro).

        Returns:
            Filename string: ce-{account}-{scope}-{tool}-{start}-{end}-{gran}-{group}.json
        """
        return (
            f"ce-{self._account_id}-{scope}-{tool}-{start.isoformat()}-"
            f"{end.isoformat()}-{gran}-{group}.json"
        )

    def _is_cache_fresh(self, path: Path) -> bool:
        """Check whether a cache file's mtime is within the TTL window.

        Args:
            path: Path to the cache file.

        Returns:
            True if the file exists and was modified less than cache_ttl_hours ago.
        """
        if not path.exists():
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age = datetime.now(tz=timezone.utc) - mtime
        return age < timedelta(hours=self._cache_ttl_hours)

    def get_cost_and_usage(
        self,
        start_time: date,
        end_time: date,
        granularity: str = "DAILY",
        group_by: Optional[dict] = None,
        cache_tool: Optional[str] = None,
        service_filter: Optional[dict[str, Any]] = None,
        cache_scope: str = "bedrock-legacy",
    ) -> dict:
        """Query Cost Explorer for scoped SERVICE costs with caching.

        Args:
            start_time: Inclusive start date for the query.
            end_time: Inclusive end date for the query.
            granularity: DAILY or MONTHLY granularity.
            group_by: Optional GroupBy dict with Type and Key fields,
                e.g. {"Type": "DIMENSION", "Key": "USAGE_TYPE"}.
            cache_tool: Optional cache filename tool segment (e.g. "cost-trend").
                When omitted, derived from group_by (cost-summary or cost-by-{key}).
            service_filter: CE Filter dict (Bedrock ecosystem OR or Kiro).
            cache_scope: Scope segment for cache key uniqueness.

        Returns:
            Raw Cost Explorer response dict.

        Raises:
            ExecutorError: If the Cost Explorer API call fails.
        """
        # Derive tool name and group string for cache key
        if cache_tool is not None:
            tool = cache_tool
            group_str = group_by.get("Key", "none") if group_by else "none"
        elif group_by is None:
            tool = "cost-summary"
            group_str = "none"
        else:
            key = group_by.get("Key", "none")
            tool = f"cost-by-{key.lower().replace('_', '-')}"
            group_str = key

        if service_filter is None:
            service_filter = {
                "Dimensions": {
                    "Key": "SERVICE",
                    "Values": ["Amazon Bedrock"],
                }
            }

        cache_filename = self._cache_key(
            tool, start_time, end_time, granularity, group_str, cache_scope
        )
        cache_path = self._cache_dir / cache_filename

        today_utc = datetime.now(tz=timezone.utc).date()
        is_current_day = end_time == today_utc

        # Cache lookup (skip if end_time is today)
        if not is_current_day and self._is_cache_fresh(cache_path):
            try:
                cached_data = cache_path.read_text(encoding="utf-8")
                return json.loads(cached_data)
            except (OSError, json.JSONDecodeError):
                # Treat as cache miss — fall through to API call
                pass

        # Build Cost Explorer request parameters
        # TimePeriod.End is exclusive (end_time + 1 day)
        ce_end = end_time + timedelta(days=1)

        params: dict = {
            "TimePeriod": {
                "Start": start_time.isoformat(),
                "End": ce_end.isoformat(),
            },
            "Granularity": granularity,
            "Metrics": ["UnblendedCost"],
            "Filter": service_filter,
        }

        if group_by is not None:
            params["GroupBy"] = [group_by]

        # Execute the Cost Explorer API call
        try:
            response = self._ce_client.get_cost_and_usage(**params)
        except (BotoCoreError, ClientError) as exc:
            raise ExecutorError(
                f"Cost Explorer query failed for account {self._account_id}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        # Strip response metadata before caching/returning
        response.pop("ResponseMetadata", None)

        # Cache write (skip if end_time is today)
        if not is_current_day:
            try:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps(response, default=str), encoding="utf-8"
                )
            except OSError:
                # Cache write failure is non-fatal — we still return the result
                pass

        return response
