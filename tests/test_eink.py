from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from copilot_usage_meter.eink import (
    DEFAULT_2IN13_DRIVER_CANDIDATES,
    EPAPER_LIB_RELATIVE_PATH,
    EInkDisplay,
    EInkDisplayError,
    _build_driver_candidates,
    _build_footer,
    _ensure_gpiozero_pin_factory,
    _ensure_waveshare_epd_on_path,
)
from copilot_usage_meter.metrics import UsageSnapshot


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


def test_build_driver_candidates_prefers_requested_driver_without_duplicates() -> None:
    candidates = _build_driver_candidates("epd2in13_V4")

    assert candidates == list(DEFAULT_2IN13_DRIVER_CANDIDATES)

def test_build_driver_candidates_supports_custom_driver_before_defaults() -> None:
    candidates = _build_driver_candidates("custom-driver")

    assert candidates[0] == "custom-driver"
    assert candidates[1:] == list(DEFAULT_2IN13_DRIVER_CANDIDATES)

def test_ensure_gpiozero_pin_factory_defaults_to_lgpio_when_available() -> None:
    with patch.dict(os.environ, {}, clear=True), patch(
        "copilot_usage_meter.eink.importlib.util.find_spec",
        return_value=object(),
    ):
        _ensure_gpiozero_pin_factory()

        assert os.environ["GPIOZERO_PIN_FACTORY"] == "lgpio"

def test_ensure_waveshare_epd_on_path_adds_nested_library_path() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        candidate = Path(tmpdir) / EPAPER_LIB_RELATIVE_PATH
        candidate.mkdir(parents=True)

        def fake_find_spec(name: str):
            if name == "waveshare_epd":
                return None
            if name == "epaper":
                return SimpleNamespace(submodule_search_locations=[tmpdir])
            return None

        with patch(
            "copilot_usage_meter.eink.importlib.util.find_spec",
            side_effect=fake_find_spec,
        ), patch("copilot_usage_meter.eink.sys.path", []):
            _ensure_waveshare_epd_on_path()

            assert str(candidate) in os.sys.path

def test_build_footer_prefers_stale_reason_and_handles_no_usage_data() -> None:
    snapshot = _build_snapshot()
    no_data_snapshot = replace(snapshot, has_personal_usage_data=False)

    assert _build_footer(snapshot, stale=True, stale_reason="timeout") == "STALE: timeout"
    assert _build_footer(snapshot, stale=True, stale_reason="") == "STALE"
    assert _build_footer(no_data_snapshot, stale=False, stale_reason="") == "No personal usage data"


def test_init_wraps_driver_init_failures() -> None:
    epd = Mock()
    epd.init.side_effect = OSError("SPI unavailable")

    with (
        patch("copilot_usage_meter.eink._import_pillow", return_value=(Mock(), Mock(), Mock())),
        patch.object(EInkDisplay, "_load_epd", return_value=epd),
        patch.object(EInkDisplay, "_load_font", return_value=object()),
    ):
        with pytest.raises(EInkDisplayError) as raised:
            EInkDisplay()

    assert "Failed to initialize e-ink display" in str(raised.value)

def test_render_snapshot_wraps_driver_display_failures() -> None:
    epd = Mock()
    epd.width = 122
    epd.height = 250
    epd.getbuffer.return_value = object()
    epd.display.side_effect = RuntimeError("display busy")

    with (
        patch("copilot_usage_meter.eink._import_pillow", return_value=(Mock(), Mock(), Mock())),
        patch.object(EInkDisplay, "_load_epd", return_value=epd),
        patch.object(EInkDisplay, "_load_font", return_value=object()),
        patch.object(EInkDisplay, "_build_image", return_value=object()),
    ):
        display = EInkDisplay()

        with pytest.raises(EInkDisplayError) as raised:
            display.render_snapshot(_build_snapshot())

    assert "Failed to update e-ink display" in str(raised.value)

def test_close_ignores_driver_sleep_failures() -> None:
    epd = Mock()
    epd.sleep.side_effect = RuntimeError("busy")

    with (
        patch("copilot_usage_meter.eink._import_pillow", return_value=(Mock(), Mock(), Mock())),
        patch.object(EInkDisplay, "_load_epd", return_value=epd),
        patch.object(EInkDisplay, "_load_font", return_value=object()),
    ):
        display = EInkDisplay()

    display.close()

def test_load_epd_wraps_driver_construction_failures() -> None:
    module = SimpleNamespace(EPD=Mock(side_effect=RuntimeError("ctor failed")))
    display = object.__new__(EInkDisplay)
    package = SimpleNamespace(__path__=[])

    with (
        patch("copilot_usage_meter.eink._import_waveshare_package", return_value=package),
        patch("copilot_usage_meter.eink.importlib.import_module", return_value=module),
    ):
        with pytest.raises(EInkDisplayError) as raised:
            display._load_epd("epd2in13_V4")

    assert "Failed to create EPD instance" in str(raised.value)