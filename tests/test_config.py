import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from copilot_usage_meter.config import ConfigError, load_config, load_dotenv


def test_load_dotenv_sets_values_without_overwriting_existing_env() -> None:
    with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"GITHUB_TOKEN": "existing"}, clear=True):
        dotenv_path = Path(tmpdir) / ".env"
        dotenv_path.write_text("GITHUB_TOKEN=from-file\nREFRESH_SECONDS=30\n", encoding="utf-8")

        load_dotenv(str(dotenv_path))

        assert os.environ["GITHUB_TOKEN"] == "existing"
        assert os.environ["REFRESH_SECONDS"] == "30"


def test_load_config_requires_github_token() -> None:
    with patch("copilot_usage_meter.config.load_dotenv"), patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ConfigError) as raised:
            load_config()

    assert "GITHUB_TOKEN is required" in str(raised.value)

def test_load_config_uses_defaults_for_optional_values() -> None:
    with patch("copilot_usage_meter.config.load_dotenv"), patch.dict(
        os.environ,
        {"GITHUB_TOKEN": "test-token"},
        clear=True,
    ):
        config = load_config()

    assert config.github_token == "test-token"
    assert config.copilot_license is None
    assert config.copilot_monthly_quota is None
    assert config.refresh_seconds == 10
    assert config.output_mode == "both"
    assert config.eink_driver_module == "auto"
    assert config.eink_rotation == 0
    assert config.api_version == "2026-03-10"
    assert config.request_timeout_seconds == 15.0
    assert config.max_retries == 2
    assert config.retry_backoff_seconds == 1.5

def test_load_config_parses_explicit_values() -> None:
    with patch("copilot_usage_meter.config.load_dotenv"), patch.dict(
        os.environ,
        {
            "GITHUB_TOKEN": "test-token",
            "COPILOT_LICENSE": " Copilot Pro+ ",
            "COPILOT_MONTHLY_QUOTA": "1500",
            "REFRESH_SECONDS": "30",
            "OUTPUT_MODE": " EINK ",
            "EINK_DRIVER_MODULE": "epd2in13_V4",
            "EINK_ROTATION": "90",
            "GITHUB_API_VERSION": "2026-04-01",
            "REQUEST_TIMEOUT_SECONDS": "20",
            "REQUEST_MAX_RETRIES": "4",
            "RETRY_BACKOFF_SECONDS": "2.5",
        },
        clear=True,
    ):
        config = load_config()

    assert config.copilot_license == "Copilot Pro+"
    assert config.copilot_monthly_quota == 1500.0
    assert config.refresh_seconds == 30
    assert config.output_mode == "eink"
    assert config.eink_driver_module == "epd2in13_V4"
    assert config.eink_rotation == 90
    assert config.api_version == "2026-04-01"
    assert config.request_timeout_seconds == 20.0
    assert config.max_retries == 4
    assert config.retry_backoff_seconds == 2.5

def test_load_config_rejects_invalid_rotation() -> None:
    with patch("copilot_usage_meter.config.load_dotenv"), patch.dict(
        os.environ,
        {"GITHUB_TOKEN": "test-token", "EINK_ROTATION": "45"},
        clear=True,
    ):
        with pytest.raises(ConfigError) as raised:
            load_config()

    assert "EINK_ROTATION must be one of" in str(raised.value)

def test_load_config_rejects_invalid_output_mode() -> None:
    with patch("copilot_usage_meter.config.load_dotenv"), patch.dict(
        os.environ,
        {"GITHUB_TOKEN": "test-token", "OUTPUT_MODE": "paper"},
        clear=True,
    ):
        with pytest.raises(ConfigError) as raised:
            load_config()

    assert "OUTPUT_MODE must be one of" in str(raised.value)