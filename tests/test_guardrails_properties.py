"""Property-based tests for guardrail enforcement.

# Feature: aws-cost-analytics, Property 4: Guardrail action allowlist is exact-match only
# Feature: aws-cost-analytics, Property 5: Guardrail requires Amazon Bedrock service filter

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

Tests use Hypothesis to verify universal properties of the GuardrailEnforcer:
- Property 4: Only exact "GetCostAndUsage" or "GetDimensionValues" are accepted
- Property 5: Filters must contain a Bedrock ecosystem SERVICE filter entry
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from aws_cost_analytics.guardrails import (
    ALLOWED_ACTIONS,
    REQUIRED_SERVICE_FILTER,
    GuardrailEnforcer,
    GuardrailError,
)


# Valid action for use in Property 5 tests (isolates filter logic)
VALID_ACTION = "GetCostAndUsage"

# Valid filters containing a Bedrock ecosystem SERVICE value
VALID_FILTERS = [
    {"Type": "DIMENSION", "Key": "SERVICE", "Values": ["Amazon Bedrock"]},
    {
        "Type": "DIMENSION",
        "Key": "SERVICE",
        "Values": ["Claude Sonnet 4.5 (Amazon Bedrock Edition)"],
    },
]


# --- Strategies ---

# Strategy that generates arbitrary strings that are NOT exact allowed actions
def not_allowed_action_strategy():
    """Generate strings that are not exactly in ALLOWED_ACTIONS."""
    return st.text(min_size=0, max_size=200).filter(lambda s: s not in ALLOWED_ACTIONS)


# Strategy that generates case variants of allowed actions (e.g., "getcostAndUsage")
def case_variant_strategy():
    """Generate case variants of allowed actions that differ from the exact match."""
    allowed = list(ALLOWED_ACTIONS)
    return st.sampled_from(allowed).flatmap(
        lambda action: st.builds(
            lambda indices, a=action: "".join(
                c.swapcase() if i in indices else c for i, c in enumerate(a)
            ),
            indices=st.frozensets(st.integers(min_value=0, max_value=len(action) - 1), min_size=1),
        )
    ).filter(lambda s: s not in ALLOWED_ACTIONS)


# Strategy that generates prefixed/suffixed versions of allowed actions
def prefix_suffix_strategy():
    """Generate strings that contain an allowed action as a substring but aren't exact."""
    allowed = list(ALLOWED_ACTIONS)
    prefix = st.text(min_size=1, max_size=10)
    suffix = st.text(min_size=1, max_size=10)
    return st.one_of(
        # Prefix + action
        st.tuples(prefix, st.sampled_from(allowed)).map(lambda t: t[0] + t[1]),
        # Action + suffix
        st.tuples(st.sampled_from(allowed), suffix).map(lambda t: t[0] + t[1]),
        # Prefix + action + suffix
        st.tuples(prefix, st.sampled_from(allowed), suffix).map(lambda t: t[0] + t[1] + t[2]),
    )


# Strategy for filter dicts without the required Bedrock SERVICE filter
def filter_without_bedrock_strategy():
    """Generate filter lists that do NOT contain the required Bedrock service filter."""
    # Generate arbitrary filter dicts that won't match the Bedrock requirement
    non_bedrock_filter = st.fixed_dictionaries({
        "Type": st.text(min_size=1, max_size=20),
        "Key": st.text(min_size=1, max_size=20),
        "Values": st.lists(st.text(min_size=1, max_size=50), min_size=0, max_size=5),
    }).filter(
        lambda f: not (f.get("Key") == "SERVICE" and "Amazon Bedrock" in f.get("Values", []))
    )
    return st.lists(non_bedrock_filter, min_size=0, max_size=5)


# Strategy for wrong service values (SERVICE key present but not Amazon Bedrock)
def wrong_service_value_strategy():
    """Generate filter lists with Key=SERVICE but wrong Values (not Amazon Bedrock)."""
    wrong_service = st.text(min_size=1, max_size=50).filter(
        lambda s: "Bedrock" not in s and s != "Amazon Bedrock"
    )
    wrong_filter = st.fixed_dictionaries({
        "Type": st.just("DIMENSION"),
        "Key": st.just("SERVICE"),
        "Values": st.lists(wrong_service, min_size=1, max_size=5),
    })
    return st.lists(wrong_filter, min_size=1, max_size=3)


# --- Property 4: Guardrail action allowlist is exact-match only ---


class TestProperty4ActionAllowlist:
    """Property 4: Guardrail action allowlist is exact-match only.

    For any action string, the GuardrailEnforcer SHALL accept it if and only if
    it is exactly "GetCostAndUsage" or "GetDimensionValues". Strings that are
    prefixes, suffixes, superstrings, or case-variants of the allowed actions
    SHALL be rejected.

    **Validates: Requirements 3.1, 3.2, 3.3**
    """

    @given(action=st.sampled_from(sorted(ALLOWED_ACTIONS)))
    @settings(max_examples=100)
    def test_allowed_actions_are_accepted(self, action):
        """Exact allowed actions should pass validation.

        # Feature: aws-cost-analytics, Property 4: Guardrail action allowlist is exact-match only
        """
        enforcer = GuardrailEnforcer()
        # Should not raise
        enforcer.validate(action, VALID_FILTERS)

    @given(action=not_allowed_action_strategy())
    @settings(max_examples=100)
    def test_arbitrary_strings_are_rejected(self, action):
        """Arbitrary strings not in the allowlist should be rejected.

        # Feature: aws-cost-analytics, Property 4: Guardrail action allowlist is exact-match only
        """
        enforcer = GuardrailEnforcer()
        with pytest.raises(GuardrailError):
            enforcer.validate(action, VALID_FILTERS)

    @given(action=case_variant_strategy())
    @settings(max_examples=100)
    def test_case_variants_are_rejected(self, action):
        """Case variants of allowed actions should be rejected (exact match only).

        # Feature: aws-cost-analytics, Property 4: Guardrail action allowlist is exact-match only
        """
        enforcer = GuardrailEnforcer()
        with pytest.raises(GuardrailError):
            enforcer.validate(action, VALID_FILTERS)

    @given(action=prefix_suffix_strategy())
    @settings(max_examples=100)
    def test_prefixed_suffixed_actions_are_rejected(self, action):
        """Actions with prefixes or suffixes should be rejected (not prefix matching).

        # Feature: aws-cost-analytics, Property 4: Guardrail action allowlist is exact-match only
        """
        enforcer = GuardrailEnforcer()
        with pytest.raises(GuardrailError):
            enforcer.validate(action, VALID_FILTERS)


# --- Property 5: Guardrail requires Amazon Bedrock service filter ---


class TestProperty5BedrockFilter:
    """Property 5: Guardrail requires Amazon Bedrock service filter.

    For any list of filters, the GuardrailEnforcer SHALL accept it if and only
    if it contains an entry with Key=SERVICE and Values containing "Amazon Bedrock".
    Filter lists that omit this entry or substitute a different service value
    SHALL be rejected.

    **Validates: Requirements 3.4, 3.5**
    """

    @given(extra_filters=st.lists(
        st.fixed_dictionaries({
            "Type": st.text(min_size=1, max_size=20),
            "Key": st.text(min_size=1, max_size=20).filter(lambda k: k != "SERVICE"),
            "Values": st.lists(st.text(min_size=1, max_size=30), min_size=0, max_size=3),
        }),
        min_size=0,
        max_size=4,
    ))
    @settings(max_examples=100)
    def test_valid_filters_with_bedrock_entry_accepted(self, extra_filters):
        """Filter lists containing the Bedrock SERVICE entry should pass.

        # Feature: aws-cost-analytics, Property 5: Guardrail requires Amazon Bedrock service filter
        """
        enforcer = GuardrailEnforcer()
        filters = extra_filters + [REQUIRED_SERVICE_FILTER]
        # Should not raise regardless of other filters present
        enforcer.validate(VALID_ACTION, filters)

    @given(filters=filter_without_bedrock_strategy())
    @settings(max_examples=100)
    def test_filters_without_bedrock_are_rejected(self, filters):
        """Filter lists missing the Bedrock SERVICE entry should be rejected.

        # Feature: aws-cost-analytics, Property 5: Guardrail requires Amazon Bedrock service filter
        """
        enforcer = GuardrailEnforcer()
        with pytest.raises(GuardrailError):
            enforcer.validate(VALID_ACTION, filters)

    @given(filters=wrong_service_value_strategy())
    @settings(max_examples=100)
    def test_wrong_service_values_are_rejected(self, filters):
        """Filter lists with SERVICE key but wrong value should be rejected.

        # Feature: aws-cost-analytics, Property 5: Guardrail requires Amazon Bedrock service filter
        """
        enforcer = GuardrailEnforcer()
        with pytest.raises(GuardrailError):
            enforcer.validate(VALID_ACTION, filters)

    @settings(max_examples=100)
    @given(data=st.data())
    def test_empty_filter_list_is_rejected(self, data):
        """An empty filter list should always be rejected.

        # Feature: aws-cost-analytics, Property 5: Guardrail requires Amazon Bedrock service filter
        """
        enforcer = GuardrailEnforcer()
        with pytest.raises(GuardrailError):
            enforcer.validate(VALID_ACTION, [])
