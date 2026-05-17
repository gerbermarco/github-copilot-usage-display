from __future__ import annotations

import importlib
import importlib.util
import os
import pkgutil
import sys
from pathlib import Path
from typing import Any, Optional

from .metrics import UsageSnapshot

DEFAULT_2IN13_DRIVER_CANDIDATES = (
    "epd2in13_V4",
    "epd2in13_V3",
    "epd2in13_V2",
    "epd2in13",
)
EPAPER_LIB_RELATIVE_PATH = Path("e-Paper") / "RaspberryPi_JetsonNano" / "python" / "lib"
EINK_DRIVER_ERRORS = (AttributeError, OSError, RuntimeError)
EINK_DRIVER_CONSTRUCTION_ERRORS = EINK_DRIVER_ERRORS + (TypeError,)


class EInkDisplayError(RuntimeError):
    """Raised when the e-ink display cannot be initialized or updated."""


class EInkDisplay:
    def __init__(self, driver_module: str = "auto", rotation: int = 0) -> None:
        if rotation not in {0, 90, 180, 270}:
            raise EInkDisplayError("E-ink rotation must be one of: 0, 90, 180, 270")

        self._Image, self._ImageDraw, self._ImageFont = _import_pillow()
        self._driver_module = driver_module
        self._rotation = rotation
        self._epd = self._load_epd(driver_module)

        self._title_font = self._load_font(size=18, bold=True)
        self._body_font = self._load_font(size=14, bold=False)
        self._body_bold_font = self._load_font(size=14, bold=True)
        self._metric_font = self._load_font(size=24, bold=True)
        self._small_font = self._load_font(size=12, bold=False)

        try:
            self._epd.init()
            self._clear()
        except EINK_DRIVER_ERRORS as exc:
            raise EInkDisplayError(f"Failed to initialize e-ink display: {exc}") from exc

    def render_snapshot(self, snapshot: UsageSnapshot, stale: bool = False, stale_reason: str = "") -> None:
        image = self._build_image(snapshot, stale=stale, stale_reason=stale_reason)

        try:
            display_buffer = self._epd.getbuffer(image)
            self._epd.display(display_buffer)
        except EINK_DRIVER_ERRORS as exc:
            raise EInkDisplayError(f"Failed to update e-ink display: {exc}") from exc

    def close(self) -> None:
        try:
            sleep = getattr(self._epd, "sleep", None)
            if callable(sleep):
                sleep()
        except EINK_DRIVER_ERRORS:
            # Device shutdown failures should not crash app exit.
            return

    def _load_epd(self, driver_module: str) -> Any:
        waveshare_package = _import_waveshare_package()
        candidates = _build_driver_candidates(driver_module)

        for candidate in candidates:
            module_path = f"waveshare_epd.{candidate}"

            try:
                module = importlib.import_module(module_path)
            except ModuleNotFoundError as exc:
                if exc.name == module_path:
                    continue
                raise EInkDisplayError(
                    f"Failed importing Waveshare driver module '{module_path}': missing dependency '{exc.name}'."
                ) from exc

            epd_class = getattr(module, "EPD", None)
            if epd_class is None:
                continue

            try:
                return epd_class()
            except EINK_DRIVER_CONSTRUCTION_ERRORS as exc:
                raise EInkDisplayError(f"Failed to create EPD instance from '{module_path}': {exc}") from exc

        available_drivers = _list_available_2in13_drivers(waveshare_package)
        available_text = ", ".join(available_drivers) if available_drivers else "none detected"
        requested = (driver_module or "").strip() or DEFAULT_2IN13_DRIVER_CANDIDATES[0]
        raise EInkDisplayError(
            "Could not import a supported Waveshare 2.13-inch driver module. "
            f"Requested: '{requested}'. Available: {available_text}. "
            "Set EINK_DRIVER_MODULE to one of the available values."
        )

    def _clear(self) -> None:
        clear = getattr(self._epd, "Clear", None)
        if not callable(clear):
            return

        try:
            clear(0xFF)
        except TypeError:
            clear()

    def _build_image(self, snapshot: UsageSnapshot, stale: bool, stale_reason: str):
        panel_width = int(getattr(self._epd, "width", 122))
        panel_height = int(getattr(self._epd, "height", 250))

        canvas_width = max(panel_width, panel_height)
        canvas_height = min(panel_width, panel_height)

        image = self._Image.new("1", (canvas_width, canvas_height), 255)
        draw = self._ImageDraw.Draw(image)

        margin = 6
        inner_left = margin + 8
        inner_right = canvas_width - margin - 8

        draw.rectangle((margin, margin, canvas_width - margin - 1, canvas_height - margin - 1), outline=0, width=2)

        percent_used = _usage_percentage(snapshot)
        percent_text = _format_percentage(percent_used)
        license_text = (snapshot.license_name or "Copilot").strip()

        title_height = _text_height(draw, self._title_font)
        body_height = _text_height(draw, self._body_font)
        premium_title_height = _text_height(draw, self._body_bold_font)
        metric_height = _text_height(draw, self._metric_font)
        metric_suffix_height = _text_height(draw, self._small_font)
        metric_block_height = max(metric_height, metric_suffix_height)
        bar_height = 12

        content_top = margin + 8
        content_bottom = canvas_height - margin - 8
        available_height = max(0, content_bottom - content_top)
        content_height = title_height + body_height + premium_title_height + metric_block_height + bar_height
        gap_values = _distribute_gap_space(
            total_space=max(0, available_height - content_height),
            slot_count=4,
            minimum_gap=2,
        )
        # Keep spacing around the percentage row visually even (top and bottom).
        metric_surround_gap = gap_values[2] + gap_values[3]
        if metric_surround_gap % 2 != 0:
            # Borrow one pixel from an earlier gap so top/bottom metric gaps can match exactly.
            for donor_index in (1, 0):
                if gap_values[donor_index] <= 0:
                    continue
                gap_values[donor_index] -= 1
                metric_surround_gap += 1
                break

        even_metric_gap = metric_surround_gap // 2
        gap_values[2] = even_metric_gap
        gap_values[3] = metric_surround_gap - even_metric_gap

        y = content_top
        draw.text((inner_left, y), _truncate(license_text, 26), font=self._title_font, fill=0)
        y += title_height + gap_values[0]

        draw.text((inner_left, y), _truncate(f"@{snapshot.username}", 30), font=self._body_font, fill=0)
        y += body_height + gap_values[1]

        draw.text((inner_left, y), "Premium requests", font=self._body_bold_font, fill=0)
        y += premium_title_height + gap_values[2]

        metric_text = percent_text
        metric_suffix = "used"
        draw.text((inner_left, y), metric_text, font=self._metric_font, fill=0)

        suffix_x = inner_left + _text_width(draw, f"{metric_text} ", self._metric_font)
        suffix_y = y + max(0, metric_height - metric_suffix_height - 1)
        draw.text((suffix_x, suffix_y), metric_suffix, font=self._small_font, fill=0)
        y += metric_block_height

        bar_top = y + gap_values[3]
        bar_top = min(bar_top, max(content_top, content_bottom - bar_height))
        bar_bottom = bar_top + bar_height - 1
        bar_width = max(40, inner_right - inner_left)
        bar_right = inner_left + bar_width

        draw.rectangle((inner_left, bar_top, bar_right, bar_bottom), outline=0, fill=255, width=1)

        ratio = _percentage_to_ratio(percent_used)
        filled_width = int(round((bar_width - 2) * ratio))
        if filled_width > 0:
            draw.rectangle((inner_left + 1, bar_top + 1, inner_left + 1 + filled_width, bar_bottom - 1), fill=0)

        footer = _build_footer(snapshot, stale=stale, stale_reason=stale_reason)
        if footer:
            footer_text = _truncate(footer, 30)
            footer_width = _text_width(draw, footer_text, self._small_font)
            draw.text((canvas_width - margin - footer_width - 2, margin + 2), footer_text, font=self._small_font, fill=0)

        if self._rotation:
            image = image.rotate(self._rotation, expand=True)

        return image

    def _load_font(self, size: int, bold: bool):
        if bold:
            candidates = (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            )
        else:
            candidates = (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            )

        for path in candidates:
            try:
                return self._ImageFont.truetype(path, size=size)
            except OSError:
                continue

        return self._ImageFont.load_default()


def _import_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise EInkDisplayError(
            "Pillow is required for e-ink rendering. Install dependencies with:\n"
            "python -m venv .venv\n"
            ". .venv/bin/activate\n"
            "pip install -r requirements.txt"
        ) from exc

    return Image, ImageDraw, ImageFont


def _import_waveshare_package():
    _ensure_gpiozero_pin_factory()
    _ensure_waveshare_epd_on_path()

    try:
        return importlib.import_module("waveshare_epd")
    except ModuleNotFoundError as exc:
        raise EInkDisplayError(
            "Could not import Waveshare Python drivers. Install dependencies with:\n"
            "python -m venv .venv\n"
            ". .venv/bin/activate\n"
            "pip install -r requirements.txt\n"
            "Then run with './.venv/bin/python run.py'."
        ) from exc


def _ensure_gpiozero_pin_factory() -> None:
    if os.getenv("GPIOZERO_PIN_FACTORY"):
        return

    if importlib.util.find_spec("lgpio") is not None:
        os.environ["GPIOZERO_PIN_FACTORY"] = "lgpio"


def _ensure_waveshare_epd_on_path() -> None:
    if importlib.util.find_spec("waveshare_epd") is not None:
        return

    epaper_spec = importlib.util.find_spec("epaper")
    if epaper_spec is None or not epaper_spec.submodule_search_locations:
        return

    for root in epaper_spec.submodule_search_locations:
        candidate = Path(root) / EPAPER_LIB_RELATIVE_PATH
        if not candidate.is_dir():
            continue

        candidate_path = str(candidate)
        if candidate_path not in sys.path:
            sys.path.append(candidate_path)


def _build_driver_candidates(driver_module: str) -> list[str]:
    requested = (driver_module or "").strip()
    if requested.lower() == "auto":
        requested = ""

    candidates: list[str] = []
    if requested:
        candidates.append(requested)

    for candidate in DEFAULT_2IN13_DRIVER_CANDIDATES:
        if candidate not in candidates:
            candidates.append(candidate)

    return candidates


def _list_available_2in13_drivers(waveshare_package: Any) -> list[str]:
    package_path = getattr(waveshare_package, "__path__", None)
    if package_path is None:
        return []

    drivers = [module.name for module in pkgutil.iter_modules(package_path) if module.name.startswith("epd2in13")]
    drivers.sort()
    return drivers


def _usage_percentage(snapshot: UsageSnapshot) -> Optional[float]:
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


def _percentage_to_ratio(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    clamped = min(max(value, 0.0), 100.0)
    return clamped / 100.0


def _build_footer(snapshot: UsageSnapshot, stale: bool, stale_reason: str) -> str:
    if stale and stale_reason:
        return f"STALE: {stale_reason}"
    if stale:
        return "STALE"
    if not snapshot.has_personal_usage_data:
        return "No personal usage data"
    return ""


def _truncate(text: str, width: int) -> str:
    normalized = text.strip()
    if len(normalized) <= width:
        return normalized
    if width <= 1:
        return normalized[:width]
    return normalized[: width - 1] + "..."


def _text_height(draw, font) -> int:
    try:
        bbox = draw.textbbox((0, 0), "Ag", font=font)
        return bbox[3] - bbox[1]
    except AttributeError:
        return font.getsize("Ag")[1]


def _text_width(draw, text: str, font) -> int:
    try:
        return int(draw.textlength(text, font=font))
    except AttributeError:
        return font.getsize(text)[0]


def _distribute_gap_space(total_space: int, slot_count: int, minimum_gap: int) -> list[int]:
    if slot_count <= 0:
        return []

    if total_space <= 0:
        return [0] * slot_count

    minimum_total = minimum_gap * slot_count
    if total_space <= minimum_total:
        base_gap = total_space // slot_count
        remainder = total_space % slot_count
    else:
        extra = total_space - minimum_total
        base_gap = minimum_gap + (extra // slot_count)
        remainder = extra % slot_count

    gaps = [base_gap] * slot_count
    for index in range(remainder):
        gaps[index] += 1

    return gaps
