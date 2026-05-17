from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

PREMIUM_USAGE_SOURCE = "/users/{username}/settings/billing/premium_request/usage"

QUANTITY_FIELD_PRIORITY = (
    "grossQuantity",
    "gross_quantity",
    "quantity",
    "usedQuantity",
    "used_quantity",
    "netQuantity",
    "net_quantity",
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
    premium_requests_used: float
    premium_net_amount_usd: float
    monthly_quota: float | None
    top_models: List[ModelUsage]
    has_personal_usage_data: bool


def build_usage_snapshot(
    username: str,
    premium_usage_payload: Dict[str, Any],
    fetched_at_utc: datetime,
    monthly_quota: float | None = None,
    license_name: str | None = None,
) -> UsageSnapshot:
    usage_items = [item for item in premium_usage_payload.get("usageItems", []) if isinstance(item, dict)]
    copilot_items = [item for item in usage_items if _item_is_copilot(item)]
    selected_items = copilot_items if copilot_items else usage_items
    resolved_license_name = _normalize_license_name(license_name) or _extract_license_name(premium_usage_payload)

    premium_requests_used = sum(_extract_quantity(item) for item in selected_items)
    premium_net_amount_usd = sum(_extract_amount(item) for item in selected_items)

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
        source=PREMIUM_USAGE_SOURCE.format(username=username),
        license_name=resolved_license_name,
        premium_requests_used=premium_requests_used,
        premium_net_amount_usd=premium_net_amount_usd,
        monthly_quota=monthly_quota,
        top_models=top_models,
        has_personal_usage_data=len(selected_items) > 0,
    )


def _item_is_copilot(item: Dict[str, Any]) -> bool:
    product = str(item.get("product", "")).lower()
    sku = str(item.get("sku", "")).lower()
    return "copilot" in product or "copilot" in sku


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


def _extract_model(item: Dict[str, Any]) -> str:
    model = item.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    return "unknown"


def _extract_license_name(premium_usage_payload: Dict[str, Any]) -> str | None:
    for field in LICENSE_FIELD_PRIORITY:
        candidate = _normalize_license_name(premium_usage_payload.get(field))
        if candidate:
            return candidate

    usage_items = premium_usage_payload.get("usageItems", [])
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
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return 0.0
    return 0.0
