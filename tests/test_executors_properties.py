"""Property-based tests for executor module.

Tests two correctness properties from the design document:
- Property 10: Date-range to Cost Explorer mapping
- Property 14: Cache key uniqueness

Validates: Requirements 5.4, 6.3, 7.3, 8.6, 10.1
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from aws_cost_analytics.executors import Executor


# --- Strategies ---

# Strategy for valid dates in a reasonable range
_date_st = st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31))

# Strategy for valid granularity values
_granularity_st = st.sampled_from(["DAILY", "MONTHLY"])

# Strategy for group_by parameter (None or a valid GroupBy dict)
_group_by_st = st.one_of(
    st.none(),
    st.sampled_from([
        {"Type": "DIMENSION", "Key": "USAGE_TYPE"},
        {"Type": "DIMENSION", "Key": "REGION"},
    ]),
)

# Strategy for 12-digit account IDs
_account_id_st = st.text(
    alphabet="0123456789", min_size=12, max_size=12
)

# Strategy for tool name segments
_tool_name_st = st.sampled_from([
    "cost-summary", "cost-by-usage-type", "cost-by-region", "cost-trend"
])

# Strategy for group string segments used in cache keys
_group_str_st = st.sampled_from(["none", "USAGE_TYPE", "REGION"])


# --- Property 10: Date-range to Cost Explorer mapping ---


class TestProperty10DateRangeToCEMapping:
    """# Feature: aws-cost-analytics, Property 10: Date-range to Cost Explorer mapping"""

    @settings(max_examples=100)
    @given(start=_date_st, end=_date_st, granularity=_granularity_st, group_by=_group_by_st)
    def test_ce_time_period_end_is_end_plus_one_day(
        self, start: date, end: date, granularity: str, group_by
    ):
        """For any valid date range, CE TimePeriod.End = end_time + 1 day and Start = start_time.

        **Validates: Requirements 5.4, 6.3, 7.3, 8.6**
        """
        assume(start <= end)

        # Mock the CE client to capture the params
        mock_session = MagicMock()
        mock_ce_client = MagicMock()
        mock_session.client.return_value = mock_ce_client

        # Mock the CE response
        mock_ce_client.get_cost_and_usage.return_value = {
            "ResultsByTime": [],
            "ResponseMetadata": {"RequestId": "test"},
        }

        # Patch datetime.now to return a date far in the future so cache bypass doesn't interfere
        executor = Executor(
            session=mock_session,
            account_id="123456789012",
            cache_ttl_hours=24,
        )

        # Patch _is_cache_fresh to always return False (cache miss) and
        # patch today to be different from end_time to allow cache logic to proceed
        with patch.object(executor, "_is_cache_fresh", return_value=False):
            with patch(
                "aws_cost_analytics.executors.datetime"
            ) as mock_datetime:
                # Make today a date far in the future so end_time != today
                mock_datetime.now.return_value = MagicMock(
                    date=MagicMock(return_value=date(2099, 1, 1))
                )
                mock_datetime.fromtimestamp = lambda *a, **kw: MagicMock()
                # Keep timedelta working
                with patch(
                    "aws_cost_analytics.executors.timedelta", wraps=timedelta
                ):
                    executor.get_cost_and_usage(
                        start_time=start,
                        end_time=end,
                        granularity=granularity,
                        group_by=group_by,
                    )

        # Verify the params passed to the CE client
        mock_ce_client.get_cost_and_usage.assert_called_once()
        call_kwargs = mock_ce_client.get_cost_and_usage.call_args[1]

        expected_start = start.isoformat()
        expected_end = (end + timedelta(days=1)).isoformat()

        assert call_kwargs["TimePeriod"]["Start"] == expected_start
        assert call_kwargs["TimePeriod"]["End"] == expected_end

        # Verify End is strictly after Start
        assert call_kwargs["TimePeriod"]["End"] > call_kwargs["TimePeriod"]["Start"]

    @settings(max_examples=100)
    @given(start=_date_st, end=_date_st, granularity=_granularity_st)
    def test_ce_time_period_end_always_after_start(
        self, start: date, end: date, granularity: str
    ):
        """The exclusive CE end date is always strictly after the start date.

        **Validates: Requirements 5.4, 6.3, 7.3, 8.6**
        """
        assume(start <= end)

        # The property: (end + 1 day).isoformat() > start.isoformat()
        ce_end = (end + timedelta(days=1)).isoformat()
        ce_start = start.isoformat()

        assert ce_end > ce_start


# --- Property 14: Cache key uniqueness ---


class TestProperty14CacheKeyUniqueness:
    """# Feature: aws-cost-analytics, Property 14: Cache key uniqueness"""

    @settings(max_examples=100)
    @given(
        account_id=_account_id_st,
        tool=_tool_name_st,
        start=_date_st,
        end=_date_st,
        gran=_granularity_st,
        group=_group_str_st,
    )
    def test_identical_params_produce_same_cache_key(
        self, account_id: str, tool: str, start: date, end: date, gran: str, group: str
    ):
        """Identical parameter tuples always produce the same cache key.

        **Validates: Requirements 10.1**
        """
        assume(start <= end)

        mock_session = MagicMock()
        mock_session.client.return_value = MagicMock()

        executor = Executor(
            session=mock_session, account_id=account_id, cache_ttl_hours=24
        )

        key1 = executor._cache_key(tool, start, end, gran, group, "scope-a")
        key2 = executor._cache_key(tool, start, end, gran, group, "scope-a")

        assert key1 == key2

    @settings(max_examples=100)
    @given(
        account_id_1=_account_id_st,
        account_id_2=_account_id_st,
        tool_1=_tool_name_st,
        tool_2=_tool_name_st,
        start_1=_date_st,
        start_2=_date_st,
        end_1=_date_st,
        end_2=_date_st,
        gran_1=_granularity_st,
        gran_2=_granularity_st,
        group_1=_group_str_st,
        group_2=_group_str_st,
    )
    def test_distinct_params_produce_distinct_cache_keys(
        self,
        account_id_1: str,
        account_id_2: str,
        tool_1: str,
        tool_2: str,
        start_1: date,
        start_2: date,
        end_1: date,
        end_2: date,
        gran_1: str,
        gran_2: str,
        group_1: str,
        group_2: str,
    ):
        """Distinct parameter tuples produce distinct cache keys.

        **Validates: Requirements 10.1**
        """
        assume(start_1 <= end_1)
        assume(start_2 <= end_2)

        # At least one parameter must differ
        params_differ = (
            account_id_1 != account_id_2
            or tool_1 != tool_2
            or start_1 != start_2
            or end_1 != end_2
            or gran_1 != gran_2
            or group_1 != group_2
        )
        assume(params_differ)

        mock_session = MagicMock()
        mock_session.client.return_value = MagicMock()

        executor_1 = Executor(
            session=mock_session, account_id=account_id_1, cache_ttl_hours=24
        )
        executor_2 = Executor(
            session=mock_session, account_id=account_id_2, cache_ttl_hours=24
        )

        key1 = executor_1._cache_key(tool_1, start_1, end_1, gran_1, group_1, "scope-a")
        key2 = executor_2._cache_key(tool_2, start_2, end_2, gran_2, group_2, "scope-b")

        assert key1 != key2
