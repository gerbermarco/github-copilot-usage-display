from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from .config import ConfigError, VALID_OUTPUT_MODES, load_config
from .console import render_snapshot
from .eink import EInkDisplay, EInkDisplayError
from .github_client import GitHubApiError, GitHubClient
from .metrics import build_usage_snapshot


def _parse_output_mode_arg(raw_value: str) -> str:
    return raw_value.strip().lower()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print GitHub Copilot personal billing usage stats every N seconds."
    )
    parser.add_argument(
        "--refresh-seconds",
        type=int,
        default=None,
        help="Refresh interval in seconds (default: use REFRESH_SECONDS or 10).",
    )
    parser.add_argument(
        "--output-mode",
        type=_parse_output_mode_arg,
        choices=sorted(VALID_OUTPUT_MODES),
        default=None,
        help="Render snapshots to console, eink, or both (default: use OUTPUT_MODE or both).",
    )
    return parser.parse_args()


def _apply_cli_overrides(config, args: argparse.Namespace):
    overrides = {}

    if args.refresh_seconds is not None:
        if args.refresh_seconds <= 0:
            raise ConfigError("--refresh-seconds must be greater than 0")
        overrides["refresh_seconds"] = args.refresh_seconds

    output_mode = getattr(args, "output_mode", None)
    if output_mode is not None:
        overrides["output_mode"] = output_mode

    if overrides:
        return replace(config, **overrides)

    return config


def _billing_404_hint(username: str) -> str:
    return (
        "Billing endpoint returned 404. Per GitHub billing usage docs, this usually means one of: \n"
        "- Token permissions are insufficient (use a fine-grained PAT with user Plan permission set to read).\n"
        "- The account does not expose personal billing usage for this endpoint (for example not on required billing platform).\n"
        "- Copilot usage is billed through an organization or enterprise, not directly to the personal account.\n"
        f"Endpoint called: /users/{username}/settings/billing/premium_request/usage"
    )


def _uses_console_output(output_mode: str) -> bool:
    return output_mode in {"console", "both"}


def _uses_eink_output(output_mode: str) -> bool:
    return output_mode in {"eink", "both"}


def _emit_snapshot(
    snapshot,
    stale: bool,
    stale_reason: str,
    output_mode: str,
    eink_display: Optional[EInkDisplay],
) -> None:
    if _uses_console_output(output_mode):
        print(
            render_snapshot(
                snapshot,
                stale=stale,
                stale_reason=stale_reason,
            )
        )
        print()

    if _uses_eink_output(output_mode) and eink_display is not None:
        try:
            eink_display.render_snapshot(snapshot, stale=stale, stale_reason=stale_reason)
        except EInkDisplayError as exc:
            print(f"E-ink display update failed: {exc}", file=sys.stderr)


def run() -> int:
    args = _parse_args()

    try:
        config = load_config()
        config = _apply_cli_overrides(config, args)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    client = GitHubClient(config)

    try:
        authenticated_username = client.get_authenticated_username()
    except GitHubApiError as exc:
        print(f"Failed to resolve username: {exc}", file=sys.stderr)
        return 3

    username = authenticated_username

    eink_display: Optional[EInkDisplay] = None
    if _uses_eink_output(config.output_mode):
        try:
            eink_display = EInkDisplay(
                driver_module=config.eink_driver_module,
                rotation=config.eink_rotation,
            )
        except EInkDisplayError as exc:
            print(f"E-ink display initialization failed: {exc}", file=sys.stderr)
            return 4

    print(f"Starting meter for user '{username}' with {config.refresh_seconds}s refresh interval.")
    print("Press Ctrl+C to stop.\n")

    last_snapshot = None
    printed_404_hint = False

    try:
        while True:
            fetched_at = datetime.now(timezone.utc)
            try:
                payload = client.get_user_premium_request_usage(
                    username=username,
                    year=fetched_at.year,
                    month=fetched_at.month,
                    product="Copilot",
                )
                snapshot = build_usage_snapshot(
                    username=username,
                    premium_usage_payload=payload,
                    fetched_at_utc=fetched_at,
                    monthly_quota=config.copilot_monthly_quota,
                    license_name=config.copilot_license,
                )
                _emit_snapshot(
                    snapshot,
                    stale=False,
                    stale_reason="",
                    output_mode=config.output_mode,
                    eink_display=eink_display,
                )
                last_snapshot = snapshot
            except GitHubApiError as exc:
                if exc.status_code == 404 and not printed_404_hint:
                    print(_billing_404_hint(username), file=sys.stderr)
                    printed_404_hint = True

                if last_snapshot is None:
                    print(f"[{fetched_at.strftime('%Y-%m-%d %H:%M:%SZ')}] API error: {exc}", file=sys.stderr)
                else:
                    _emit_snapshot(
                        last_snapshot,
                        stale=True,
                        stale_reason=str(exc),
                        output_mode=config.output_mode,
                        eink_display=eink_display,
                    )

            time.sleep(config.refresh_seconds)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    finally:
        if eink_display is not None:
            eink_display.close()


if __name__ == "__main__":
    raise SystemExit(run())
