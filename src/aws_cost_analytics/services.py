"""Bedrock ecosystem and Kiro service discovery for Cost Explorer filters.

Discovers all SERVICE dimension values matching \"Bedrock\" via
GetDimensionValues and builds OR filters for GetCostAndUsage queries.
Discovery results are cached under ~/.cache/aws-cost-analytics/.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from aws_cost_analytics.guardrails import GuardrailEnforcer, GuardrailError
from aws_cost_analytics.paths import services_cache_path

BEDROCK_SEARCH_STRING = "Bedrock"
KIRO_SERVICE = "Kiro"
FALLBACK_BEDROCK_SERVICES = ["Amazon Bedrock"]
SERVICES_CACHE_VERSION = 3
DISCOVERY_LOOKBACK_DAYS = 90


def _is_incomplete_discovery(services: list[str]) -> bool:
    """True when discovery result should not be trusted or cached."""
    return services == list(FALLBACK_BEDROCK_SERVICES)


class ServiceDiscoveryError(Exception):
    """Raised when service discovery fails."""

    pass


def service_list_hash(services: list[str]) -> str:
    """Stable short hash for a sorted service name list (cache key segment)."""
    payload = ",".join(sorted(services))
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def build_service_filter(services: list[str]) -> dict[str, Any]:
    """Build a Cost Explorer Filter for one or more SERVICE values."""
    if not services:
        raise ValueError("At least one service is required for a cost filter")
    if len(services) == 1:
        return {"Dimensions": {"Key": "SERVICE", "Values": [services[0]]}}
    return {
        "Or": [
            {"Dimensions": {"Key": "SERVICE", "Values": [service]}}
            for service in services
        ]
    }


def build_kiro_filter() -> dict[str, Any]:
    """Build a Cost Explorer Filter for Kiro IDE spend."""
    return {"Dimensions": {"Key": "SERVICE", "Values": [KIRO_SERVICE]}}


def _is_services_cache_fresh(path: Path, cache_ttl_hours: int) -> bool:
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age = datetime.now(tz=timezone.utc) - mtime
    return age < timedelta(hours=cache_ttl_hours)


def _load_services_cache(path: Path) -> list[str] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != SERVICES_CACHE_VERSION:
            return None
        services = data.get("services")
        if isinstance(services, list) and all(isinstance(s, str) for s in services):
            return services
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _write_services_cache(path: Path, services: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": SERVICES_CACHE_VERSION, "services": services}, indent=2),
        encoding="utf-8",
    )


def discover_bedrock_services(
    ce_client,
    cache_ttl_hours: int,
    cache_path: Path | None = None,
) -> list[str]:
    """Return Bedrock ecosystem SERVICE names, using a cached discovery file when fresh."""
    resolved_cache_path = cache_path or services_cache_path()
    if _is_services_cache_fresh(resolved_cache_path, cache_ttl_hours):
        cached = _load_services_cache(resolved_cache_path)
        if cached and not _is_incomplete_discovery(cached):
            return cached

    today = datetime.now(tz=timezone.utc).date()
    start = today - timedelta(days=DISCOVERY_LOOKBACK_DAYS)
    end = today + timedelta(days=1)

    enforcer = GuardrailEnforcer()
    try:
        enforcer.validate_get_dimension_values("SERVICE", BEDROCK_SEARCH_STRING)
        response = ce_client.get_dimension_values(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Dimension="SERVICE",
            SearchString=BEDROCK_SEARCH_STRING,
        )
    except (GuardrailError, BotoCoreError, ClientError) as exc:
        raise ServiceDiscoveryError(
            f"Failed to discover Bedrock ecosystem services: {exc}"
        ) from exc

    services = sorted(
        {
            item["Value"]
            for item in response.get("DimensionValues", [])
            if item.get("Value")
        }
    )
    if not services:
        return list(FALLBACK_BEDROCK_SERVICES)

    if not _is_incomplete_discovery(services):
        try:
            _write_services_cache(resolved_cache_path, services)
        except OSError:
            pass

    return services


def prepare_bedrock_cost_filter(
    ce_client, cache_ttl_hours: int
) -> tuple[dict[str, Any], str]:
    """Discover services, validate guardrails, return (CE filter, cache scope hash)."""
    services = discover_bedrock_services(ce_client, cache_ttl_hours)
    ce_filter = build_service_filter(services)
    GuardrailEnforcer().validate_cost_filter(
        "GetCostAndUsage", ce_filter, frozenset(services)
    )
    return ce_filter, f"bedrock-{service_list_hash(services)}"


def prepare_kiro_cost_filter() -> tuple[dict[str, Any], str]:
    """Return (CE filter, cache scope) for Kiro-only queries."""
    ce_filter = build_kiro_filter()
    GuardrailEnforcer().validate_cost_filter(
        "GetCostAndUsage", ce_filter, frozenset({KIRO_SERVICE})
    )
    return ce_filter, "kiro"
