from datetime import datetime, timezone

from copilot_usage_meter.metrics import build_usage_snapshot


def test_prefers_gross_quantity_for_usage_over_net_quantity() -> None:
    payload = {
        "usageItems": [
            {
                "product": "Copilot",
                "grossQuantity": 280,
                "discountQuantity": 280,
                "netQuantity": 0,
                "netAmount": 0.0,
                "model": "gpt-4.1",
            }
        ],
    }

    snapshot = build_usage_snapshot(
        username="octocat",
        usage_summary_payload=payload,
        fetched_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert snapshot.credits_used == 280
    assert snapshot.credit_net_amount_usd == 0.0

def test_prefers_explicit_copilot_items_when_other_products_are_present() -> None:
    payload = {
        "usageItems": [
            {
                "product": "Actions",
                "grossQuantity": 999,
                "netAmount": 10.0,
                "model": "n/a",
            },
            {
                "product": "Copilot",
                "grossQuantity": 18,
                "netAmount": 0.72,
                "model": "gpt-4.1",
            },
        ],
    }

    snapshot = build_usage_snapshot(
        username="octocat",
        usage_summary_payload=payload,
        fetched_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert snapshot.credits_used == 18
    assert snapshot.top_models[0].model == "gpt-4.1"

def test_marks_empty_payload_as_no_personal_usage_data() -> None:
    snapshot = build_usage_snapshot(
        username="octocat",
        usage_summary_payload={"usageItems": []},
        fetched_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert not snapshot.has_personal_usage_data
    assert snapshot.top_models == []

def test_carries_manual_included_credits_into_snapshot() -> None:
    snapshot = build_usage_snapshot(
        username="octocat",
        usage_summary_payload={
            "usageItems": [
                {
                    "product": "Copilot",
                    "grossQuantity": 18,
                    "netAmount": 0.72,
                    "model": "gpt-4.1",
                }
            ]
        },
        fetched_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
        included_credits=1500,
    )

    assert snapshot.included_credits == 1500
    assert snapshot.usage_percent == 1.2


def test_prefers_payload_included_credits_over_manual_fallback() -> None:
    snapshot = build_usage_snapshot(
        username="octocat",
        usage_summary_payload={
            "includedCredits": 7000,
            "usageItems": [
                {
                    "product": "Copilot",
                    "grossQuantity": 1149.6,
                    "netAmount": 0,
                    "sku": "Copilot Premium Request",
                }
            ],
        },
        fetched_at_utc=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
        included_credits=1500,
    )

    assert snapshot.included_credits == 7000
    assert round(snapshot.usage_percent or 0, 1) == 16.4

def test_prefers_explicit_license_name_when_provided() -> None:
    snapshot = build_usage_snapshot(
        username="octocat",
        usage_summary_payload={
            "usageItems": [
                {
                    "product": "Copilot",
                    "sku": "Copilot Premium Request",
                    "grossQuantity": 18,
                    "netAmount": 0.72,
                    "model": "gpt-4.1",
                }
            ]
        },
        fetched_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
        license_name="Copilot Pro+",
    )

    assert snapshot.license_name == "Copilot Pro+"

def test_extracts_license_from_payload_when_available() -> None:
    snapshot = build_usage_snapshot(
        username="octocat",
        usage_summary_payload={
            "license": "Copilot Business",
            "usageItems": [
                {
                    "product": "Copilot",
                    "grossQuantity": 18,
                    "netAmount": 0.72,
                    "model": "gpt-4.1",
                }
            ],
        },
        fetched_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert snapshot.license_name == "Copilot Business"