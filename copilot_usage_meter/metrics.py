from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

USAGE_SUMMARY_SOURCE = "/users/{username}/settings/billing/usage/summary"

QUANTITY_FIELD_PRIORITY = (
    "grossQuantity",
    "gross_quantity",
    "quantity",
    "usedQuantity",
    "used_quantity",
    "netQuantity",
    "net_quantity",
)
INCLUDED_CREDITS_FIELD_PRIORITY = (
    "includedCredits",
    "included_credits",
    "includedQuantity",
    "included_quantity",
    "monthlyIncludedCredits",
    "monthly_included_credits",
    "monthlyQuota",
    "monthly_quota",
    "creditLimit",
    "credit_limit",
    "quota",
    "limit",
)
PERCENT_FIELD_PRIORITY = (
    "usagePercentage",
    "usage_percentage",
    "percentUsed",
    "percent_used",
    "usedPercentage",
    "used_percentage",
)
AMOUNT_FIELD_PRIORITY = (
    "netAmount",
    "grossAmount",
    "net_amount",
    "gross_amount",
)
LICENSE_FIELD_PRIORITY = (
    "license",
    "licenseType",
    "license_type",
    "plan",
    "planType",
    "plan_type",
    "subscription",
    "subscriptionType",
    "subscription_type",
    "copilotPlan",
    "copilot_plan",
)


@dataclass(frozen=True)
class ModelUsage:
    model: str
    requests: float


@dataclass(frozen=True)
class UsageSnapshot:
    fetched_at_utc: datetime
    username: str
    source: str
    license_name: str | None
    credits_used: float
    credit_net_amount_usd: float
    included_credits: float | None
    usage_percent: float | None
    top_models: List[ModelUsage]
    has_personal_usage_data: bool


def build_usage_snapshot(
    username: str,
    usage_summary_payload: Dict[str, Any],
    fetched_at_utc: datetime,
    included_credits: float | None = None,
    license_name: str | None = None,
) -> UsageSnapshot:
    usage_items = [item for item in usage_summary_payload.get("usageItems", []) if isinstance(item, dict)]
    copilot_items = [item for item in usage_items if _item_is_copilot(item)]
    selected_items = copilot_items if copilot_items else usage_items
    resolved_license_name = _normalize_license_name(license_name) or _extract_license_name(usage_summary_payload)

    resolved_included_credits = _extract_included_credits(usage_summary_payload, selected_items)
    if resolved_included_credits is None:
        resolved_included_credits = included_credits

    credits_used = sum(_extract_quantity(item) for item in selected_items)
    credit_net_amount_usd = sum(_extract_amount(item) for item in selected_items)
    usage_percent = _extract_usage_percent(usage_summary_payload, selected_items)
    if usage_percent is None:
        usage_percent = _calculate_usage_percent(credits_used, resolved_included_credits)

    model_totals: Dict[str, float] = defaultdict(float)
    for item in selected_items:
        model_totals[_extract_model(item)] += _extract_quantity(item)

    top_models = [
        ModelUsage(model=model, requests=requests)
        for model, requests in sorted(model_totals.items(), key=lambda pair: pair[1], reverse=True)[:3]
    ]

    return UsageSnapshot(
        fetched_at_utc=fetched_at_utc.astimezone(timezone.utc),
        username=username,
        source=USAGE_SUMMARY_SOURCE.format(username=username),
        license_name=resolved_license_name,
        credits_used=credits_used,
        credit_net_amount_usd=credit_net_amount_usd,
        included_credits=resolved_included_credits,
        usage_percent=usage_percent,
        top_models=top_models,
        has_personal_usage_data=len(selected_items) > 0,
    )


def _item_is_copilot(item: Dict[str, Any]) -> bool:
    product = str(item.get("product", "")).lower()
    sku = str(item.get("sku", "")).lower()
    return "copilot" in product or "copilot" in sku or "premium request" in sku


def _extract_quantity(item: Dict[str, Any]) -> float:
    for field in QUANTITY_FIELD_PRIORITY:
        if field in item:
            return _to_float(item.get(field))
    return 0.0


def _extract_amount(item: Dict[str, Any]) -> float:
    for field in AMOUNT_FIELD_PRIORITY:
        if field in item:
            return _to_float(item.get(field))
    return 0.0


def _extract_included_credits(payload: Dict[str, Any], usage_items: Iterable[Dict[str, Any]]) -> float | None:
    payload_value = _first_numeric_field(payload, INCLUDED_CREDITS_FIELD_PRIORITY)
    if payload_value is not None:
        return payload_value

    for item in usage_items:
        item_value = _first_numeric_field(item, INCLUDED_CREDITS_FIELD_PRIORITY)
        if item_value is not None:
            return item_value

    return None


def _extract_usage_percent(payload: Dict[str, Any], usage_items: Iterable[Dict[str, Any]]) -> float | None:
    payload_value = _normalize_percent(_first_numeric_field(payload, PERCENT_FIELD_PRIORITY))
    if payload_value is not None:
        return payload_value

    for item in usage_items:
        item_value = _normalize_percent(_first_numeric_field(item, PERCENT_FIELD_PRIORITY))
        if item_value is not None:
            return item_value

    return None


def _calculate_usage_percent(credits_used: float, included_credits: float | None) -> float | None:
    if included_credits is None or included_credits <= 0:
        return None
    return (credits_used / included_credits) * 100.0


def _extract_model(item: Dict[str, Any]) -> str:
    model = item.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    sku = item.get("sku")
    if isinstance(sku, str) and sku.strip():
        return sku.strip()
    return "unknown"


def _extract_license_name(usage_summary_payload: Dict[str, Any]) -> str | None:
    for field in LICENSE_FIELD_PRIORITY:
        candidate = _normalize_license_name(usage_summary_payload.get(field))
        if candidate:
            return candidate

    usage_items = usage_summary_payload.get("usageItems", [])
    if not isinstance(usage_items, list):
        return None

    for item in usage_items:
        if not isinstance(item, dict):
            continue

        for field in LICENSE_FIELD_PRIORITY:
            candidate = _normalize_license_name(item.get(field))
            if candidate:
                return candidate

        sku = _normalize_license_name(item.get("sku"))
        if sku and "copilot" in sku.lower():
            return sku

        product = _normalize_license_name(item.get("product"))
        if product and "copilot" in product.lower():
            return product

    return None


def _normalize_license_name(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return None


def _to_float(value: Any) -> float:
    parsed = _to_optional_float(value)
    if parsed is None:
        return 0.0
    return parsed


def _first_numeric_field(payload: Dict[str, Any], fields: Iterable[str]) -> float | None:
    for field in fields:
        if field in payload:
            return _to_optional_float(payload.get(field))
    return None


def _to_optional_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _normalize_percent(value: float | None) -> float | None:
    if value is None:
        return None
    if 0 < value <= 1:
        return value * 100.0
    return value
