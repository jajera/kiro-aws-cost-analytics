"""Shared test fixtures for AWS Cost Analytics test suite."""

import pytest


@pytest.fixture
def sample_account_id():
    """Provide a sample 12-digit AWS account ID for tests."""
    return "123456789012"


@pytest.fixture
def tmp_config(tmp_path):
    """Provide a temporary directory for config file tests."""
    return tmp_path


@pytest.fixture
def tmp_cache_dir(tmp_path):
    """Provide a temporary directory for cache file tests."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return cache_dir
