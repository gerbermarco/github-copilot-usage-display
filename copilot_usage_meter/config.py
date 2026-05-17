from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class ConfigError(ValueError):
    """Raised when application configuration is invalid."""


VALID_OUTPUT_MODES = {"console", "eink", "both"}


@dataclass(frozen=True)
class AppConfig:
    github_token: str
    copilot_license: Optional[str]
    copilot_monthly_quota: Optional[float]
    refresh_seconds: int
    output_mode: str
    eink_driver_module: str
    eink_rotation: int
    api_version: str
    request_timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float


def load_dotenv(dotenv_path: str = ".env") -> None:
    """Load simple KEY=VALUE pairs from a .env file into os.environ."""
    path = Path(dotenv_path)
    if not path.exists() or not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _parse_int(name: str, raw_value: Optional[str], default: int, minimum: int = 1) -> int:
    if raw_value is None or raw_value.strip() == "":
        return default

    try:
        parsed = int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got: {raw_value!r}") from exc

    if parsed < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got: {parsed}")

    return parsed


def _parse_float(name: str, raw_value: Optional[str], default: float, minimum: float = 0.0) -> float:
    if raw_value is None or raw_value.strip() == "":
        return default

    try:
        parsed = float(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got: {raw_value!r}") from exc

    if parsed < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got: {parsed}")

    return parsed


def _parse_optional_float(name: str, raw_value: Optional[str], minimum: float = 0.0) -> Optional[float]:
    if raw_value is None or raw_value.strip() == "":
        return None

    try:
        parsed = float(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got: {raw_value!r}") from exc

    if parsed < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got: {parsed}")

    return parsed


def _parse_optional_string(raw_value: Optional[str]) -> Optional[str]:
    if raw_value is None:
        return None

    cleaned = raw_value.strip()
    if not cleaned:
        return None
    return cleaned


def _parse_rotation(raw_value: Optional[str]) -> int:
    rotation = _parse_int("EINK_ROTATION", raw_value, default=0, minimum=0)
    if rotation not in {0, 90, 180, 270}:
        raise ConfigError("EINK_ROTATION must be one of: 0, 90, 180, 270")
    return rotation


def _parse_output_mode(raw_value: Optional[str]) -> str:
    if raw_value is None or raw_value.strip() == "":
        return "both"

    output_mode = raw_value.strip().lower()
    if output_mode not in VALID_OUTPUT_MODES:
        allowed_values = ", ".join(sorted(VALID_OUTPUT_MODES))
        raise ConfigError(f"OUTPUT_MODE must be one of: {allowed_values}")

    return output_mode


def load_config() -> AppConfig:
    load_dotenv()

    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "GITHUB_TOKEN is required. Create a fine-grained PAT with user 'Plan: read' permission."
        )

    copilot_monthly_quota = _parse_optional_float(
        "COPILOT_MONTHLY_QUOTA",
        os.getenv("COPILOT_MONTHLY_QUOTA"),
        minimum=0.0,
    )
    copilot_license = _parse_optional_string(os.getenv("COPILOT_LICENSE"))
    refresh_seconds = _parse_int("REFRESH_SECONDS", os.getenv("REFRESH_SECONDS"), default=10)
    output_mode = _parse_output_mode(os.getenv("OUTPUT_MODE"))
    eink_driver_module = _parse_optional_string(os.getenv("EINK_DRIVER_MODULE")) or "auto"
    eink_rotation = _parse_rotation(os.getenv("EINK_ROTATION"))

    api_version = os.getenv("GITHUB_API_VERSION", "2026-03-10").strip() or "2026-03-10"

    request_timeout_seconds = _parse_float(
        "REQUEST_TIMEOUT_SECONDS",
        os.getenv("REQUEST_TIMEOUT_SECONDS"),
        default=15.0,
        minimum=0.1,
    )
    max_retries = _parse_int("REQUEST_MAX_RETRIES", os.getenv("REQUEST_MAX_RETRIES"), default=2, minimum=0)
    retry_backoff_seconds = _parse_float(
        "RETRY_BACKOFF_SECONDS",
        os.getenv("RETRY_BACKOFF_SECONDS"),
        default=1.5,
        minimum=0.0,
    )

    return AppConfig(
        github_token=token,
        copilot_license=copilot_license,
        copilot_monthly_quota=copilot_monthly_quota,
        refresh_seconds=refresh_seconds,
        output_mode=output_mode,
        eink_driver_module=eink_driver_module,
        eink_rotation=eink_rotation,
        api_version=api_version,
        request_timeout_seconds=request_timeout_seconds,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
