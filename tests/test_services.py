"""Unit tests for Bedrock ecosystem service discovery and filters."""

import json
from unittest.mock import MagicMock

import pytest

from aws_cost_analytics.guardrails import GuardrailEnforcer, GuardrailError
from aws_cost_analytics.services import (
    build_kiro_filter,
    build_service_filter,
    prepare_kiro_cost_filter,
    service_list_hash,
)


class TestBuildServiceFilter:
    def test_single_service_uses_dimensions(self):
        filt = build_service_filter(["Amazon Bedrock"])
        assert filt == {
            "Dimensions": {"Key": "SERVICE", "Values": ["Amazon Bedrock"]}
        }

    def test_multiple_services_uses_or(self):
        services = [
            "Amazon Bedrock",
            "Claude Sonnet 4.5 (Amazon Bedrock Edition)",
        ]
        filt = build_service_filter(services)
        assert "Or" in filt
        assert len(filt["Or"]) == 2


class TestGuardrailCostFilter:
    def test_bedrock_ecosystem_or_filter_accepted(self):
        services = [
            "Amazon Bedrock",
            "Claude Sonnet 4.5 (Amazon Bedrock Edition)",
        ]
        filt = build_service_filter(services)
        GuardrailEnforcer().validate_cost_filter(
            "GetCostAndUsage", filt, frozenset(services)
        )

    def test_disallowed_service_rejected(self):
        filt = build_service_filter(["Amazon EC2"])
        with pytest.raises(GuardrailError, match="disallowed"):
            GuardrailEnforcer().validate_cost_filter(
                "GetCostAndUsage", filt, frozenset({"Amazon Bedrock"})
            )

    def test_kiro_filter(self):
        filt, scope = prepare_kiro_cost_filter()
        assert scope == "kiro"
        assert filt == build_kiro_filter()


class TestServiceListHash:
    def test_stable_hash(self):
        services = ["Amazon Bedrock", "Claude Sonnet 4.5 (Amazon Bedrock Edition)"]
        assert service_list_hash(services) == service_list_hash(list(reversed(services)))


class TestDiscoverBedrockServices:
    def test_incomplete_cache_is_ignored(self, tmp_path):
        cache_path = tmp_path / "ce-services-bedrock.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"version": 3, "services": ["Amazon Bedrock"]}),
            encoding="utf-8",
        )

        mock_ce = MagicMock()
        mock_ce.get_dimension_values.return_value = {
            "DimensionValues": [
                {"Value": "Amazon Bedrock"},
                {"Value": "Claude Sonnet 4.5 (Amazon Bedrock Edition)"},
            ]
        }

        from aws_cost_analytics.services import discover_bedrock_services

        services = discover_bedrock_services(mock_ce, cache_ttl_hours=24, cache_path=cache_path)
        assert "Claude Sonnet 4.5 (Amazon Bedrock Edition)" in services
        mock_ce.get_dimension_values.assert_called_once()
