"""Read-only guardrail enforcement.

Maintains an explicit allowlist of permitted Cost Explorer actions
(GetCostAndUsage, GetDimensionValues) and enforces scoped SERVICE
filters for the Bedrock ecosystem and optional Kiro queries.

All outbound Cost Explorer API calls must pass guardrail validation
before execution.
"""

from typing import Any

ALLOWED_ACTIONS: frozenset[str] = frozenset({"GetCostAndUsage", "GetDimensionValues"})

BEDROCK_DISCOVERY_DIMENSION = "SERVICE"
BEDROCK_DISCOVERY_SEARCH = "Bedrock"
KIRO_SERVICE = "Kiro"

# Backward-compatible alias for tests
REQUIRED_SERVICE_FILTER: dict[str, Any] = {
    "Type": "DIMENSION",
    "Key": "SERVICE",
    "Values": ["Amazon Bedrock"],
}


def extract_service_values(ce_filter: dict[str, Any]) -> frozenset[str]:
    """Extract SERVICE dimension values from a CE filter dict."""
    values: set[str] = set()
    if "Dimensions" in ce_filter:
        dim = ce_filter["Dimensions"]
        if dim.get("Key") == "SERVICE":
            values.update(dim.get("Values", []))
    if "Or" in ce_filter:
        for clause in ce_filter["Or"]:
            values.update(extract_service_values(clause))
    return frozenset(values)


class GuardrailError(Exception):
    """Raised when a guardrail check fails (blocked action or invalid filter)."""

    pass


class GuardrailEnforcer:
    """Enforces read-only guardrails on Cost Explorer API calls."""

    def validate(self, action: str, filters: list[dict[str, Any]]) -> None:
        """Legacy validate for list-style filter checks in existing tests."""
        if action not in ALLOWED_ACTIONS:
            raise GuardrailError(
                f"Action '{action}' is not permitted. "
                f"Allowed actions: {sorted(ALLOWED_ACTIONS)}"
            )
        if not self._legacy_has_bedrock_filter(filters):
            raise GuardrailError(
                "Required Bedrock ecosystem service filter is missing. "
                "All queries must include SERVICE values from the Bedrock "
                "ecosystem (e.g. Amazon Bedrock or *Bedrock Edition* services)."
            )

    def validate_get_dimension_values(
        self, dimension: str, search_string: str | None
    ) -> None:
        """Validate GetDimensionValues is scoped to Bedrock service discovery."""
        if dimension != BEDROCK_DISCOVERY_DIMENSION:
            raise GuardrailError(
                f"Dimension '{dimension}' is not permitted for discovery. "
                f"Only '{BEDROCK_DISCOVERY_DIMENSION}' is allowed."
            )
        if search_string != BEDROCK_DISCOVERY_SEARCH:
            raise GuardrailError(
                f"SearchString '{search_string}' is not permitted. "
                f"Only '{BEDROCK_DISCOVERY_SEARCH}' is allowed."
            )

    def validate_cost_filter(
        self,
        action: str,
        ce_filter: dict[str, Any],
        allowed_services: frozenset[str],
    ) -> None:
        """Validate a GetCostAndUsage filter uses only approved SERVICE values."""
        if action not in ALLOWED_ACTIONS:
            raise GuardrailError(
                f"Action '{action}' is not permitted. "
                f"Allowed actions: {sorted(ALLOWED_ACTIONS)}"
            )

        filter_services = extract_service_values(ce_filter)
        if not filter_services:
            raise GuardrailError(
                "Cost filter must include at least one SERVICE dimension value."
            )

        disallowed = filter_services - allowed_services
        if disallowed:
            raise GuardrailError(
                "Filter contains disallowed SERVICE values: "
                f"{sorted(disallowed)}. "
                f"Allowed values: {sorted(allowed_services)}"
            )

        if allowed_services == frozenset({KIRO_SERVICE}):
            if filter_services != frozenset({KIRO_SERVICE}):
                raise GuardrailError(
                    "Kiro queries must filter only SERVICE = Kiro."
                )
            return

        if not all(self._is_bedrock_ecosystem_service(s) for s in filter_services):
            raise GuardrailError(
                "Bedrock ecosystem filters may only include SERVICE values "
                "associated with Bedrock (discovered via GetDimensionValues)."
            )

    def _is_bedrock_ecosystem_service(self, service: str) -> bool:
        return service == "Amazon Bedrock" or "Bedrock" in service

    def _legacy_has_bedrock_filter(self, filters: list[dict[str, Any]]) -> bool:
        """Check list-style filters for any Bedrock ecosystem SERVICE value."""
        for f in filters:
            if f.get("Key") != "SERVICE":
                continue
            for value in f.get("Values", []):
                if self._is_bedrock_ecosystem_service(value):
                    return True
        return False
