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
        premium_usage_payload=payload,
        fetched_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert snapshot.premium_requests_used == 280
    assert snapshot.premium_net_amount_usd == 0.0

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
        premium_usage_payload=payload,
        fetched_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert snapshot.premium_requests_used == 18
    assert snapshot.top_models[0].model == "gpt-4.1"

def test_marks_empty_payload_as_no_personal_usage_data() -> None:
    snapshot = build_usage_snapshot(
        username="octocat",
        premium_usage_payload={"usageItems": []},
        fetched_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert not snapshot.has_personal_usage_data
    assert snapshot.top_models == []

def test_carries_manual_monthly_quota_into_snapshot() -> None:
    snapshot = build_usage_snapshot(
        username="octocat",
        premium_usage_payload={
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
        monthly_quota=1500,
    )

    assert snapshot.monthly_quota == 1500

def test_prefers_explicit_license_name_when_provided() -> None:
    snapshot = build_usage_snapshot(
        username="octocat",
        premium_usage_payload={
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
        premium_usage_payload={
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