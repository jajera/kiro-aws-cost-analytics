"""Tests for default cache paths."""

from pathlib import Path

from aws_cost_analytics.paths import (
    CACHE_DIR_NAME,
    default_cache_dir,
    services_cache_path,
)


def test_default_cache_dir_under_home_cache():
    cache_dir = default_cache_dir()
    assert cache_dir == Path.home() / ".cache" / CACHE_DIR_NAME


def test_services_cache_path():
    assert services_cache_path() == default_cache_dir() / "ce-services-bedrock.json"
    custom = Path("/tmp/test-cache")
    assert services_cache_path(custom) == custom / "ce-services-bedrock.json"
