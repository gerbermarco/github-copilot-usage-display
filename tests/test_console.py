from datetime import datetime, timezone

from copilot_usage_meter.console import render_snapshot
from copilot_usage_meter.metrics import build_usage_snapshot


def _build_snapshot(
    payload: dict,
    monthly_quota: float | None = None,
    license_name: str | None = None,
    username: str = "octocat",
) -> object:
    return build_usage_snapshot(
        username=username,
        premium_usage_payload=payload,
        fetched_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
        monthly_quota=monthly_quota,
        license_name=license_name,
    )


def test_renders_compact_card_with_license_username_and_percentage() -> None:
    snapshot = _build_snapshot(
        {
            "usageItems": [
                {
                    "product": "Copilot",
                    "grossQuantity": 281,
                    "netAmount": 0.72,
                    "model": "gpt-4.1",
                }
            ],
        },
        monthly_quota=1500,
        license_name="Copilot Pro+",
    )

    output = render_snapshot(snapshot)

    assert "Copilot Pro+" in output
    assert "@octocat" in output
    assert "Premium requests" in output
    assert "\033[1m" not in output
    assert "19% used" in output
    assert "[####----------------]" in output
    assert "Premium net billed amount" not in output

def test_warns_when_no_personal_usage_data() -> None:
    snapshot = _build_snapshot(
        {
            "usageItems": [],
        }
    )

    output = render_snapshot(snapshot)

    assert "No personal usage data" in output

def test_shows_na_percentage_without_quota() -> None:
    snapshot = _build_snapshot(
        {
            "usageItems": [
                {
                    "product": "Copilot",
                    "grossQuantity": 281,
                    "netAmount": 0.0,
                    "model": "gpt-5.4",
                }
            ]
        }
    )

    output = render_snapshot(snapshot)

    assert "N/A used" in output

def test_includes_stale_marker_and_error_reason() -> None:
    snapshot = _build_snapshot(
        {
            "usageItems": [
                {
                    "product": "Copilot",
                    "grossQuantity": 281,
                    "netAmount": 0.0,
                    "model": "gpt-5.4",
                }
            ]
        },
        monthly_quota=1500,
    )

    output = render_snapshot(snapshot, stale=True, stale_reason="Network timeout")

    assert "STALE DATA" in output
    assert "Err: Network timeout" in output