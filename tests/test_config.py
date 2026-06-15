"""Unit tests for config module.

Tests config loading with missing file (defaults), valid config,
invalid region, invalid TTL, unrecognized fields, and malformed JSON.

Requirements: 1.1–1.9
"""

import json
from pathlib import Path

import pytest

from aws_cost_analytics.config import Config, ConfigError, load_config


class TestLoadConfigMissingFile:
    """Test that missing config.json returns all defaults (Req 1.6)."""

    def test_missing_file_returns_defaults(self, tmp_config):
        config_path = tmp_config / "config.json"
        result = load_config(config_path)

        assert result.region == ""
        assert result.cache_ttl_hours == 24

    def test_missing_file_does_not_raise(self, tmp_config):
        config_path = tmp_config / "nonexistent" / "config.json"
        result = load_config(config_path)

        assert isinstance(result, Config)


class TestLoadConfigValidConfig:
    """Test loading valid config files (Reqs 1.1, 1.4, 1.5)."""

    def test_valid_region_and_ttl(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"region": "us-east-1", "cache_ttl_hours": 48}))

        result = load_config(config_path)

        assert result.region == "us-east-1"
        assert result.cache_ttl_hours == 48

    def test_region_only(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"region": "eu-west-2"}))

        result = load_config(config_path)

        assert result.region == "eu-west-2"
        assert result.cache_ttl_hours == 24  # default

    def test_ttl_only(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"cache_ttl_hours": 1}))

        result = load_config(config_path)

        assert result.region == ""  # default
        assert result.cache_ttl_hours == 1

    def test_empty_json_object_uses_defaults(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text("{}")

        result = load_config(config_path)

        assert result.region == ""
        assert result.cache_ttl_hours == 24

    def test_various_valid_regions(self, tmp_config):
        valid_regions = ["us-east-1", "eu-west-2", "ap-southeast-1", "af-south-1", "me-central-1"]
        config_path = tmp_config / "config.json"

        for region in valid_regions:
            config_path.write_text(json.dumps({"region": region}))
            result = load_config(config_path)
            assert result.region == region

    def test_cache_ttl_boundary_values(self, tmp_config):
        config_path = tmp_config / "config.json"

        # Min boundary
        config_path.write_text(json.dumps({"cache_ttl_hours": 1}))
        result = load_config(config_path)
        assert result.cache_ttl_hours == 1

        # Max boundary
        config_path.write_text(json.dumps({"cache_ttl_hours": 168}))
        result = load_config(config_path)
        assert result.cache_ttl_hours == 168


class TestLoadConfigInvalidRegion:
    """Test rejection of invalid region formats (Req 1.1, 1.8)."""

    def test_invalid_region_uppercase(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"region": "US-EAST-1"}))

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)

        assert "region" in str(exc_info.value).lower()

    def test_invalid_region_no_number(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"region": "us-east"}))

        with pytest.raises(ConfigError):
            load_config(config_path)

    def test_invalid_region_random_string(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"region": "not-a-region-at-all"}))

        with pytest.raises(ConfigError):
            load_config(config_path)

    def test_invalid_region_numeric_prefix(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"region": "123-east-1"}))

        with pytest.raises(ConfigError):
            load_config(config_path)

    def test_error_message_identifies_field(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"region": "INVALID"}))

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)

        assert "region" in str(exc_info.value).lower()


class TestLoadConfigInvalidTTL:
    """Test rejection of invalid cache_ttl_hours values (Req 1.5, 1.8)."""

    def test_ttl_zero(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"cache_ttl_hours": 0}))

        with pytest.raises(ConfigError):
            load_config(config_path)

    def test_ttl_negative(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"cache_ttl_hours": -1}))

        with pytest.raises(ConfigError):
            load_config(config_path)

    def test_ttl_above_max(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"cache_ttl_hours": 169}))

        with pytest.raises(ConfigError):
            load_config(config_path)

    def test_ttl_very_large(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"cache_ttl_hours": 10000}))

        with pytest.raises(ConfigError):
            load_config(config_path)

    def test_error_message_identifies_field(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"cache_ttl_hours": 0}))

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)

        assert "cache_ttl_hours" in str(exc_info.value)


class TestLoadConfigUnrecognizedFields:
    """Test rejection of unrecognized field names (Req 1.7)."""

    def test_single_unrecognized_field(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"unknown_field": "value"}))

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)

        assert "unknown_field" in str(exc_info.value).lower() or "unrecognized" in str(exc_info.value).lower()

    def test_unrecognized_field_with_valid_fields(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({
            "region": "us-east-1",
            "cache_ttl_hours": 24,
            "extra_field": True,
        }))

        with pytest.raises(ConfigError):
            load_config(config_path)

    def test_multiple_unrecognized_fields(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"foo": 1, "bar": 2}))

        with pytest.raises(ConfigError):
            load_config(config_path)

    def test_error_message_is_descriptive(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text(json.dumps({"mystery_setting": "abc"}))

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)

        error_msg = str(exc_info.value)
        assert "mystery_setting" in error_msg.lower() or "unrecognized" in error_msg.lower()


class TestLoadConfigMalformedJSON:
    """Test rejection of malformed JSON (Req 1.9)."""

    def test_invalid_json_syntax(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text("{invalid json content")

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)

        assert "parse" in str(exc_info.value).lower() or "json" in str(exc_info.value).lower()

    def test_trailing_comma(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text('{"region": "us-east-1",}')

        with pytest.raises(ConfigError):
            load_config(config_path)

    def test_empty_file(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text("")

        with pytest.raises(ConfigError):
            load_config(config_path)

    def test_non_object_json(self, tmp_config):
        """JSON arrays or primitives are not valid configs."""
        config_path = tmp_config / "config.json"
        config_path.write_text('"just a string"')

        with pytest.raises((ConfigError, TypeError)):
            load_config(config_path)

    def test_error_indicates_parse_failure(self, tmp_config):
        config_path = tmp_config / "config.json"
        config_path.write_text("not json at all")

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_path)

        error_msg = str(exc_info.value).lower()
        assert "parse" in error_msg or "malformed" in error_msg or "json" in error_msg
