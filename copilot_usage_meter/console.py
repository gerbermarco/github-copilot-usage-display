from __future__ import annotations

from typing import Optional

from .metrics import UsageSnapshot

CARD_WIDTH = 32
CARD_CONTENT_WIDTH = CARD_WIDTH - 4


def render_snapshot(
    snapshot: UsageSnapshot,
    stale: bool = False,
    stale_reason: str = "",
) -> str:
    percent_used = _get_usage_percentage(snapshot)
    percent_text = _format_percentage(percent_used)
    bar_text = _render_usage_bar(percent_used if percent_used is not None else 0.0)
    license_text = snapshot.license_name or "Copilot"

    lines = [
        _frame_border(),
        _frame_line(license_text),
        _frame_line(f"@{snapshot.username}"),
        _frame_line("Premium requests"),
        _frame_line(f"{percent_text} used"),
        _frame_line(f"[{bar_text}]"),
    ]

    if not snapshot.has_personal_usage_data:
        lines.append(_frame_line("No personal usage data"))

    if stale:
        lines.append(_frame_line("STALE DATA"))
        if stale_reason:
            lines.append(_frame_line(f"Err: {stale_reason}"))

    lines.append(_frame_border())
    return "\n".join(lines)


def _frame_border() -> str:
    return "+" + ("-" * (CARD_WIDTH - 2)) + "+"


def _frame_line(value: str) -> str:
    trimmed = value.strip()[:CARD_CONTENT_WIDTH]
    return f"| {trimmed.ljust(CARD_CONTENT_WIDTH)} |"


def _get_usage_percentage(snapshot: UsageSnapshot) -> Optional[float]:
    if snapshot.monthly_quota is None or snapshot.monthly_quota <= 0:
        return None
    return (snapshot.premium_requests_used / snapshot.monthly_quota) * 100.0


def _format_percentage(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    if value <= 0:
        return "0%"
    if value < 1:
        return "<1%"
    return f"{int(round(value))}%"


def _render_usage_bar(percent_used: float, width: int = 20) -> str:
    clamped_percent = min(max(percent_used, 0.0), 100.0)
    filled_width = int(round((clamped_percent / 100.0) * width))
    return f"{'#' * filled_width}{'-' * (width - filled_width)}"
