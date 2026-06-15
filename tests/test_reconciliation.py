"""Unit tests for billing reconciliation."""

from datetime import date
from unittest.mock import MagicMock

from aws_cost_analytics.reconciliation import get_kiro_summary, get_record_type_summary


def test_record_type_summary_computes_gross_and_net():
    ce = MagicMock()
    ce.get_cost_and_usage.return_value = {
        "ResultsByTime": [
            {
                "Groups": [
                    {"Keys": ["FlatRateSubscription"], "Metrics": {"UnblendedCost": {"Amount": "13.70"}}},
                    {"Keys": ["Usage"], "Metrics": {"UnblendedCost": {"Amount": "2.27"}}},
                    {"Keys": ["Tax"], "Metrics": {"UnblendedCost": {"Amount": "0.06"}}},
                    {"Keys": ["Credit"], "Metrics": {"UnblendedCost": {"Amount": "-15.58"}}},
                ]
            }
        ]
    }

    summary = get_record_type_summary(ce, date(2026, 6, 1), date(2026, 6, 15))
    assert round(summary.gross_before_credits, 2) == 16.03
    assert round(summary.credits, 2) == -15.58
    assert round(summary.net_total, 2) == 0.45


def test_kiro_summary_splits_subscription_and_credits():
    ce = MagicMock()
    ce.get_cost_and_usage.side_effect = [
        {
            "ResultsByTime": [
                {
                    "Groups": [
                        {"Keys": ["FlatRateSubscription"], "Metrics": {"UnblendedCost": {"Amount": "13.70"}}},
                        {"Keys": ["Credit"], "Metrics": {"UnblendedCost": {"Amount": "-13.70"}}},
                    ]
                }
            ]
        },
        {
            "ResultsByTime": [
                {
                    "Groups": [
                        {
                            "Keys": ["USE1-KiroEnterprise-Pro"],
                            "Metrics": {"UnblendedCost": {"Amount": "13.70"}},
                        }
                    ]
                }
            ]
        },
    ]

    summary = get_kiro_summary(ce, date(2026, 6, 1), date(2026, 6, 15))
    assert summary.subscription == 13.70
    assert summary.credits == -13.70
    assert summary.net_total == 0.0
    assert summary.usage_type == "USE1-KiroEnterprise-Pro"
