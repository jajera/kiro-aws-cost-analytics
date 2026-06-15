"""Unit tests for executor caching behavior.

Tests cover Requirements 10.1–10.6:
- Cache hit (fresh file, returns without API call)
- Cache miss (expired file, calls API)
- Cache bypass when end_time == today
- Cache write on successful query
- Corrupted cache file treated as miss
- cache directory auto-creation
"""

import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aws_cost_analytics.executors import Executor, ExecutorError


# --- Helpers ---

MOCK_CE_RESPONSE = {
    "ResultsByTime": [
        {
            "TimePeriod": {"Start": "2024-01-01", "End": "2024-01-02"},
            "Total": {"UnblendedCost": {"Amount": "5.00", "Unit": "USD"}},
        }
    ],
    "ResponseMetadata": {"RequestId": "abc123"},
}

MOCK_CE_RESPONSE_STRIPPED = {
    "ResultsByTime": [
        {
            "TimePeriod": {"Start": "2024-01-01", "End": "2024-01-02"},
            "Total": {"UnblendedCost": {"Amount": "5.00", "Unit": "USD"}},
        }
    ]
}


def _make_executor(tmp_path, cache_ttl_hours=24):
    """Create an Executor with a mocked session pointing cache_dir to tmp_path."""
    mock_session = MagicMock()
    mock_ce_client = MagicMock()
    mock_session.client.return_value = mock_ce_client

    executor = Executor(mock_session, "123456789012", cache_ttl_hours)
    # Redirect cache dir to the tmp_path for isolated testing
    executor._cache_dir = tmp_path / "cache"

    return executor, mock_ce_client


# --- Tests ---


class TestCacheHit:
    """Test that a fresh cache file is returned without calling the API."""

    def test_cache_hit_returns_cached_data(self, tmp_path):
        """Validates: Requirement 10.3 — fresh cache returns without CE call."""
        executor, mock_ce_client = _make_executor(tmp_path)

        # Set up: use a past end_time (not today) so cache is checked
        start_time = date(2024, 1, 1)
        end_time = date(2024, 1, 31)

        # Create the cache directory and write a valid cache file
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Derive the expected cache key (tool="cost-summary", group="none")
        cache_filename = (
            f"ce-123456789012-bedrock-legacy-cost-summary-2024-01-01-2024-01-31-DAILY-none.json"
        )
        cache_path = cache_dir / cache_filename
        cache_path.write_text(json.dumps(MOCK_CE_RESPONSE_STRIPPED), encoding="utf-8")

        # Ensure mtime is very recent (within TTL)
        # Touch the file to set mtime to now
        os.utime(cache_path, None)

        result = executor.get_cost_and_usage(start_time, end_time, "DAILY", None)

        # Should return cached data without calling the CE client
        assert result == MOCK_CE_RESPONSE_STRIPPED
        mock_ce_client.get_cost_and_usage.assert_not_called()


class TestCacheMiss:
    """Test that an expired cache file triggers an API call."""

    def test_expired_cache_calls_api(self, tmp_path):
        """Validates: Requirement 10.3 — expired cache triggers CE call."""
        executor, mock_ce_client = _make_executor(tmp_path, cache_ttl_hours=1)

        start_time = date(2024, 1, 1)
        end_time = date(2024, 1, 31)

        # Create the cache directory and write a cache file
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_filename = (
            f"ce-123456789012-bedrock-legacy-cost-summary-2024-01-01-2024-01-31-DAILY-none.json"
        )
        cache_path = cache_dir / cache_filename
        cache_path.write_text(
            json.dumps(MOCK_CE_RESPONSE_STRIPPED), encoding="utf-8"
        )

        # Set mtime to 2 hours ago (beyond 1-hour TTL)
        old_time = time.time() - (2 * 3600)
        os.utime(cache_path, (old_time, old_time))

        # Mock the CE client response
        mock_ce_client.get_cost_and_usage.return_value = dict(MOCK_CE_RESPONSE)

        result = executor.get_cost_and_usage(start_time, end_time, "DAILY", None)

        # Should have called the CE client since cache is stale
        mock_ce_client.get_cost_and_usage.assert_called_once()
        assert result == MOCK_CE_RESPONSE_STRIPPED

    def test_nonexistent_cache_calls_api(self, tmp_path):
        """Validates: Requirement 10.3 — missing cache file triggers CE call."""
        executor, mock_ce_client = _make_executor(tmp_path)

        start_time = date(2024, 1, 1)
        end_time = date(2024, 1, 31)

        mock_ce_client.get_cost_and_usage.return_value = dict(MOCK_CE_RESPONSE)

        result = executor.get_cost_and_usage(start_time, end_time, "DAILY", None)

        mock_ce_client.get_cost_and_usage.assert_called_once()
        assert result == MOCK_CE_RESPONSE_STRIPPED


class TestCacheBypassToday:
    """Test that cache is always bypassed when end_time == today(UTC)."""

    def test_today_end_time_bypasses_cache(self, tmp_path):
        """Validates: Requirement 10.4 — end_time == today always calls CE."""
        executor, mock_ce_client = _make_executor(tmp_path)

        today_utc = datetime.now(tz=timezone.utc).date()
        start_time = today_utc - timedelta(days=30)
        end_time = today_utc

        # Create a fresh cache file that would normally be a hit
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_filename = (
            f"ce-123456789012-bedrock-legacy-cost-summary-{start_time.isoformat()}-"
            f"{end_time.isoformat()}-DAILY-none.json"
        )
        cache_path = cache_dir / cache_filename
        cache_path.write_text(json.dumps(MOCK_CE_RESPONSE_STRIPPED), encoding="utf-8")
        os.utime(cache_path, None)  # fresh mtime

        mock_ce_client.get_cost_and_usage.return_value = dict(MOCK_CE_RESPONSE)

        result = executor.get_cost_and_usage(start_time, end_time, "DAILY", None)

        # Even with fresh cache, should call CE because end_time == today
        mock_ce_client.get_cost_and_usage.assert_called_once()

    def test_today_end_time_does_not_write_cache(self, tmp_path):
        """Validates: Requirement 10.4 — end_time == today skips cache write."""
        executor, mock_ce_client = _make_executor(tmp_path)

        today_utc = datetime.now(tz=timezone.utc).date()
        start_time = today_utc - timedelta(days=7)
        end_time = today_utc

        mock_ce_client.get_cost_and_usage.return_value = dict(MOCK_CE_RESPONSE)

        executor.get_cost_and_usage(start_time, end_time, "DAILY", None)

        # The cache directory should not have been created / no files written
        cache_dir = tmp_path / "cache"
        if cache_dir.exists():
            assert list(cache_dir.iterdir()) == []


class TestCacheWrite:
    """Test that cache is written on successful query when end_time != today."""

    def test_cache_written_after_successful_query(self, tmp_path):
        """Validates: Requirement 10.2 — cache write on success."""
        executor, mock_ce_client = _make_executor(tmp_path)

        start_time = date(2024, 1, 1)
        end_time = date(2024, 1, 31)

        mock_ce_client.get_cost_and_usage.return_value = dict(MOCK_CE_RESPONSE)

        executor.get_cost_and_usage(start_time, end_time, "DAILY", None)

        # Verify cache file was written
        cache_dir = tmp_path / "cache"
        cache_filename = (
            f"ce-123456789012-bedrock-legacy-cost-summary-2024-01-01-2024-01-31-DAILY-none.json"
        )
        cache_path = cache_dir / cache_filename

        assert cache_path.exists()
        cached_data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert cached_data == MOCK_CE_RESPONSE_STRIPPED

    def test_cache_written_with_group_by(self, tmp_path):
        """Validates: Requirement 10.1, 10.2 — cache key includes group_by."""
        executor, mock_ce_client = _make_executor(tmp_path)

        start_time = date(2024, 1, 1)
        end_time = date(2024, 1, 31)
        group_by = {"Type": "DIMENSION", "Key": "USAGE_TYPE"}

        mock_ce_client.get_cost_and_usage.return_value = dict(MOCK_CE_RESPONSE)

        executor.get_cost_and_usage(start_time, end_time, "DAILY", group_by)

        # Cache key should use "cost-by-usage-type" as tool and "USAGE_TYPE" as group
        cache_dir = tmp_path / "cache"
        cache_filename = (
            f"ce-123456789012-bedrock-legacy-cost-by-usage-type-2024-01-01-2024-01-31-"
            f"DAILY-USAGE_TYPE.json"
        )
        cache_path = cache_dir / cache_filename
        assert cache_path.exists()


class TestCorruptedCache:
    """Test that corrupted cache files are treated as cache misses."""

    def test_invalid_json_treated_as_miss(self, tmp_path):
        """Validates: Requirement 10.6 — invalid JSON triggers API call."""
        executor, mock_ce_client = _make_executor(tmp_path)

        start_time = date(2024, 1, 1)
        end_time = date(2024, 1, 31)

        # Write corrupted JSON to cache
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_filename = (
            f"ce-123456789012-bedrock-legacy-cost-summary-2024-01-01-2024-01-31-DAILY-none.json"
        )
        cache_path = cache_dir / cache_filename
        cache_path.write_text("{ invalid json content !!!", encoding="utf-8")
        os.utime(cache_path, None)  # fresh mtime

        mock_ce_client.get_cost_and_usage.return_value = dict(MOCK_CE_RESPONSE)

        result = executor.get_cost_and_usage(start_time, end_time, "DAILY", None)

        # Should fall through to API call
        mock_ce_client.get_cost_and_usage.assert_called_once()
        assert result == MOCK_CE_RESPONSE_STRIPPED

    def test_empty_file_treated_as_miss(self, tmp_path):
        """Validates: Requirement 10.6 — empty file triggers API call."""
        executor, mock_ce_client = _make_executor(tmp_path)

        start_time = date(2024, 1, 1)
        end_time = date(2024, 1, 31)

        # Write empty file to cache
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_filename = (
            f"ce-123456789012-bedrock-legacy-cost-summary-2024-01-01-2024-01-31-DAILY-none.json"
        )
        cache_path = cache_dir / cache_filename
        cache_path.write_text("", encoding="utf-8")
        os.utime(cache_path, None)  # fresh mtime

        mock_ce_client.get_cost_and_usage.return_value = dict(MOCK_CE_RESPONSE)

        result = executor.get_cost_and_usage(start_time, end_time, "DAILY", None)

        mock_ce_client.get_cost_and_usage.assert_called_once()
        assert result == MOCK_CE_RESPONSE_STRIPPED


class TestDirectoryAutoCreation:
    """Test that the cache directory is created automatically."""

    def test_cache_dir_created_on_cache_write(self, tmp_path):
        """Validates: Requirement 10.5 — cache dir created if not exists."""
        executor, mock_ce_client = _make_executor(tmp_path)

        start_time = date(2024, 1, 1)
        end_time = date(2024, 1, 31)

        # Ensure the cache directory does NOT exist
        cache_dir = tmp_path / "cache"
        assert not cache_dir.exists()

        mock_ce_client.get_cost_and_usage.return_value = dict(MOCK_CE_RESPONSE)

        executor.get_cost_and_usage(start_time, end_time, "DAILY", None)

        # Directory should have been created
        assert cache_dir.exists()
        assert cache_dir.is_dir()

        # And the cache file should be written inside it
        cache_files = list(cache_dir.iterdir())
        assert len(cache_files) == 1

    def test_nested_cache_dir_created(self, tmp_path):
        """Validates: Requirement 10.5 — mkdir with parents=True."""
        executor, mock_ce_client = _make_executor(tmp_path)
        # Point cache dir to a nested path that doesn't exist
        executor._cache_dir = tmp_path / "deep" / "nested" / "cache"

        start_time = date(2024, 1, 1)
        end_time = date(2024, 1, 31)

        mock_ce_client.get_cost_and_usage.return_value = dict(MOCK_CE_RESPONSE)

        executor.get_cost_and_usage(start_time, end_time, "DAILY", None)

        assert executor._cache_dir.exists()
        assert executor._cache_dir.is_dir()
