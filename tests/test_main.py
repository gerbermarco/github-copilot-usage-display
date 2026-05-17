from argparse import Namespace
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from copilot_usage_meter.config import AppConfig, ConfigError
from copilot_usage_meter.github_client import GitHubApiError
from copilot_usage_meter.metrics import UsageSnapshot
from copilot_usage_meter.main import _apply_cli_overrides, _emit_snapshot, run


def _build_config(output_mode: str = "both") -> AppConfig:
    return AppConfig(
        github_token="test-token",
        copilot_license=None,
        copilot_monthly_quota=1500.0,
        refresh_seconds=10,
        output_mode=output_mode,
        eink_driver_module="auto",
        eink_rotation=0,
        api_version="2026-03-10",
        request_timeout_seconds=15.0,
        max_retries=2,
        retry_backoff_seconds=1.5,
    )


def _build_snapshot() -> UsageSnapshot:
    return UsageSnapshot(
        fetched_at_utc=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
        username="octocat",
        source="/users/octocat/settings/billing/premium_request/usage",
        license_name="Copilot Pro+",
        premium_requests_used=281.0,
        premium_net_amount_usd=0.72,
        monthly_quota=1500.0,
        top_models=[],
        has_personal_usage_data=True,
    )


def test_apply_cli_overrides_updates_refresh_seconds_and_output_mode() -> None:
    config = _build_config(output_mode="both")

    updated = _apply_cli_overrides(
        config,
        Namespace(refresh_seconds=30, output_mode="console"),
    )

    assert updated.refresh_seconds == 30
    assert updated.output_mode == "console"

def test_returns_two_for_config_errors() -> None:
    with (
        patch("copilot_usage_meter.main._parse_args", return_value=Namespace(refresh_seconds=None)),
        patch("copilot_usage_meter.main.load_config", side_effect=ConfigError("bad token")),
        patch("builtins.print") as print_mock,
    ):
        exit_code = run()

    assert exit_code == 2
    assert any("Configuration error" in call.args[0] for call in print_mock.call_args_list if call.args)

def test_returns_three_when_username_lookup_fails() -> None:
    client = Mock()
    client.get_authenticated_username.side_effect = GitHubApiError("boom")

    with (
        patch("copilot_usage_meter.main._parse_args", return_value=Namespace(refresh_seconds=None)),
        patch("copilot_usage_meter.main.load_config", return_value=_build_config()),
        patch("copilot_usage_meter.main.GitHubClient", return_value=client),
        patch("builtins.print") as print_mock,
    ):
        exit_code = run()

    assert exit_code == 3
    assert any("Failed to resolve username" in call.args[0] for call in print_mock.call_args_list if call.args)

def test_emits_stale_snapshot_after_api_error_when_previous_snapshot_exists() -> None:
    snapshot = _build_snapshot()
    client = Mock()
    client.get_authenticated_username.return_value = "octocat"
    client.get_user_premium_request_usage.side_effect = [
        {"usageItems": [{"product": "Copilot", "grossQuantity": 281}]},
        GitHubApiError("Network timeout"),
    ]
    eink_display = Mock()

    with (
        patch("copilot_usage_meter.main._parse_args", return_value=Namespace(refresh_seconds=None)),
        patch("copilot_usage_meter.main.load_config", return_value=_build_config()),
        patch("copilot_usage_meter.main.GitHubClient", return_value=client),
        patch("copilot_usage_meter.main.EInkDisplay", return_value=eink_display),
        patch("copilot_usage_meter.main.build_usage_snapshot", return_value=snapshot),
        patch("copilot_usage_meter.main._emit_snapshot") as emit_snapshot,
        patch("copilot_usage_meter.main.time.sleep", side_effect=[None, KeyboardInterrupt]),
        patch("builtins.print"),
    ):
        exit_code = run()

    assert exit_code == 0
    assert emit_snapshot.call_count == 2

    first_call = emit_snapshot.call_args_list[0]
    assert first_call.args[0] == snapshot
    assert not first_call.kwargs["stale"]
    assert first_call.kwargs["stale_reason"] == ""

    second_call = emit_snapshot.call_args_list[1]
    assert second_call.args[0] == snapshot
    assert second_call.kwargs["stale"]
    assert second_call.kwargs["stale_reason"] == "Network timeout"
    eink_display.close.assert_called_once_with()

def test_prints_404_hint_only_once() -> None:
    client = Mock()
    client.get_authenticated_username.return_value = "octocat"
    client.get_user_premium_request_usage.side_effect = [
        GitHubApiError("missing", status_code=404),
        GitHubApiError("missing", status_code=404),
    ]
    eink_display = Mock()

    with (
        patch("copilot_usage_meter.main._parse_args", return_value=Namespace(refresh_seconds=None)),
        patch("copilot_usage_meter.main.load_config", return_value=_build_config()),
        patch("copilot_usage_meter.main.GitHubClient", return_value=client),
        patch("copilot_usage_meter.main.EInkDisplay", return_value=eink_display),
        patch("copilot_usage_meter.main.time.sleep", side_effect=[None, KeyboardInterrupt]),
        patch("builtins.print") as print_mock,
    ):
        exit_code = run()

    hint_calls = [
        call
        for call in print_mock.call_args_list
        if call.args and "Billing endpoint returned 404" in str(call.args[0])
    ]
    assert exit_code == 0
    assert len(hint_calls) == 1
    eink_display.close.assert_called_once_with()

def test_emit_snapshot_console_only_skips_eink() -> None:
    snapshot = _build_snapshot()
    eink_display = Mock()

    with (
        patch("copilot_usage_meter.main.render_snapshot", return_value="console-card") as render_snapshot_mock,
        patch("builtins.print") as print_mock,
    ):
        _emit_snapshot(
            snapshot,
            stale=False,
            stale_reason="",
            output_mode="console",
            eink_display=eink_display,
        )

    render_snapshot_mock.assert_called_once_with(snapshot, stale=False, stale_reason="")
    assert print_mock.call_count == 2
    assert print_mock.call_args_list[0].args == ("console-card",)
    assert print_mock.call_args_list[1].args == ()
    eink_display.render_snapshot.assert_not_called()

def test_emit_snapshot_eink_only_skips_console() -> None:
    snapshot = _build_snapshot()
    eink_display = Mock()

    with (
        patch("copilot_usage_meter.main.render_snapshot") as render_snapshot_mock,
        patch("builtins.print") as print_mock,
    ):
        _emit_snapshot(
            snapshot,
            stale=True,
            stale_reason="timeout",
            output_mode="eink",
            eink_display=eink_display,
        )

    render_snapshot_mock.assert_not_called()
    print_mock.assert_not_called()
    eink_display.render_snapshot.assert_called_once_with(snapshot, stale=True, stale_reason="timeout")

def test_emit_snapshot_both_outputs_to_console_and_eink() -> None:
    snapshot = _build_snapshot()
    eink_display = Mock()

    with (
        patch("copilot_usage_meter.main.render_snapshot", return_value="console-card") as render_snapshot_mock,
        patch("builtins.print") as print_mock,
    ):
        _emit_snapshot(
            snapshot,
            stale=False,
            stale_reason="",
            output_mode="both",
            eink_display=eink_display,
        )

    render_snapshot_mock.assert_called_once_with(snapshot, stale=False, stale_reason="")
    assert print_mock.call_count == 2
    eink_display.render_snapshot.assert_called_once_with(snapshot, stale=False, stale_reason="")

def test_run_skips_eink_initialization_for_console_mode() -> None:
    snapshot = _build_snapshot()
    client = Mock()
    client.get_authenticated_username.return_value = "octocat"
    client.get_user_premium_request_usage.return_value = {"usageItems": [{"product": "Copilot", "grossQuantity": 281}]}

    with (
        patch("copilot_usage_meter.main._parse_args", return_value=Namespace(refresh_seconds=None)),
        patch("copilot_usage_meter.main.load_config", return_value=_build_config(output_mode="console")),
        patch("copilot_usage_meter.main.GitHubClient", return_value=client),
        patch("copilot_usage_meter.main.EInkDisplay") as eink_display_class,
        patch("copilot_usage_meter.main.build_usage_snapshot", return_value=snapshot),
        patch("copilot_usage_meter.main._emit_snapshot") as emit_snapshot,
        patch("copilot_usage_meter.main.time.sleep", side_effect=[KeyboardInterrupt]),
        patch("builtins.print"),
    ):
        exit_code = run()

    assert exit_code == 0
    eink_display_class.assert_not_called()
    emit_snapshot.assert_called_once()
    assert emit_snapshot.call_args.kwargs["output_mode"] == "console"
    assert emit_snapshot.call_args.kwargs["eink_display"] is None

def test_run_uses_cli_output_mode_override_over_config() -> None:
    snapshot = _build_snapshot()
    client = Mock()
    client.get_authenticated_username.return_value = "octocat"
    client.get_user_premium_request_usage.return_value = {"usageItems": [{"product": "Copilot", "grossQuantity": 281}]}

    with (
        patch(
            "copilot_usage_meter.main._parse_args",
            return_value=Namespace(refresh_seconds=None, output_mode="console"),
        ),
        patch("copilot_usage_meter.main.load_config", return_value=_build_config(output_mode="both")),
        patch("copilot_usage_meter.main.GitHubClient", return_value=client),
        patch("copilot_usage_meter.main.EInkDisplay") as eink_display_class,
        patch("copilot_usage_meter.main.build_usage_snapshot", return_value=snapshot),
        patch("copilot_usage_meter.main._emit_snapshot") as emit_snapshot,
        patch("copilot_usage_meter.main.time.sleep", side_effect=[KeyboardInterrupt]),
        patch("builtins.print"),
    ):
        exit_code = run()

    assert exit_code == 0
    eink_display_class.assert_not_called()
    emit_snapshot.assert_called_once()
    assert emit_snapshot.call_args.kwargs["output_mode"] == "console"