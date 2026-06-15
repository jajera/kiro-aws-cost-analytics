"""Property-based tests for config validation.

Tests three correctness properties from the design document:
- Property 1: Region validation accepts only valid AWS region patterns
- Property 2: Cache TTL range validation
- Property 3: Unrecognized config fields are rejected

Validates: Requirements 1.1, 1.5, 1.7
"""

import re
import string

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

from aws_cost_analytics.config import Config, ConfigError


_REGION_PATTERN = re.compile(r"^[a-z]{2,4}-[a-z]+-\d{1,2}$")


# --- Strategies ---

# Strategy that generates strings matching the valid region pattern
_valid_region_st = st.from_regex(r"[a-z]{2,4}-[a-z]+-\d{1,2}", fullmatch=True)

# Strategy that generates arbitrary text strings (may or may not match)
_arbitrary_string_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=30,
)

# Strategy for field names that are NOT recognized config fields
_RECOGNIZED_FIELDS = {"region", "cache_ttl_hours"}
_unrecognized_field_st = st.text(
    alphabet=string.ascii_lowercase + string.digits + "_",
    min_size=1,
    max_size=20,
).filter(lambda s: s not in _RECOGNIZED_FIELDS)


# --- Property 1: Region validation accepts only valid AWS region patterns ---


class TestProperty1RegionValidation:
    """# Feature: aws-cost-analytics, Property 1: Region validation accepts only valid AWS region patterns"""

    @settings(max_examples=100)
    @given(region=_valid_region_st)
    def test_valid_regions_accepted(self, region: str):
        """Valid region strings matching the pattern are always accepted.

        **Validates: Requirements 1.1**
        """
        config = Config(region=region)
        assert config.region == region

    @settings(max_examples=100)
    @given(region=_arbitrary_string_st)
    def test_invalid_regions_rejected(self, region: str):
        """Non-matching, non-empty strings are always rejected.

        **Validates: Requirements 1.1**
        """
        assume(not _REGION_PATTERN.match(region))
        assume(region != "")

        with pytest.raises(ValidationError):
            Config(region=region)

    def test_empty_region_accepted(self):
        """Empty string is a special case meaning 'resolve at runtime'.

        **Validates: Requirements 1.1**
        """
        config = Config(region="")
        assert config.region == ""


# --- Property 2: Cache TTL range validation ---


class TestProperty2CacheTTLValidation:
    """# Feature: aws-cost-analytics, Property 2: Cache TTL range validation"""

    @settings(max_examples=100)
    @given(ttl=st.integers(min_value=1, max_value=168))
    def test_valid_ttl_accepted(self, ttl: int):
        """Integer values in [1, 168] are always accepted.

        **Validates: Requirements 1.5**
        """
        config = Config(cache_ttl_hours=ttl)
        assert config.cache_ttl_hours == ttl

    @settings(max_examples=100)
    @given(ttl=st.integers(max_value=0))
    def test_ttl_below_range_rejected(self, ttl: int):
        """Values below 1 are always rejected.

        **Validates: Requirements 1.5**
        """
        with pytest.raises(ValidationError):
            Config(cache_ttl_hours=ttl)

    @settings(max_examples=100)
    @given(ttl=st.integers(min_value=169))
    def test_ttl_above_range_rejected(self, ttl: int):
        """Values above 168 are always rejected.

        **Validates: Requirements 1.5**
        """
        with pytest.raises(ValidationError):
            Config(cache_ttl_hours=ttl)


# --- Property 3: Unrecognized config fields are rejected ---


class TestProperty3UnrecognizedFieldsRejected:
    """# Feature: aws-cost-analytics, Property 3: Unrecognized config fields are rejected"""

    @settings(max_examples=100)
    @given(field_name=_unrecognized_field_st, value=st.one_of(
        st.integers(),
        st.text(max_size=10),
        st.booleans(),
    ))
    def test_unrecognized_fields_rejected(self, field_name: str, value):
        """Any field name not in {region, cache_ttl_hours} causes a ValidationError.

        **Validates: Requirements 1.7**
        """
        with pytest.raises(ValidationError) as exc_info:
            Config(**{field_name: value})

        # Verify the error identifies the unrecognized field
        error_str = str(exc_info.value)
        assert field_name in error_str or "extra" in error_str.lower()
