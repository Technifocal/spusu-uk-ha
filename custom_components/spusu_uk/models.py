"""Normalize numeric balances without guessing undocumented units."""

from dataclasses import dataclass
from math import isfinite
from typing import Any

from .api import InvalidResponse


@dataclass(frozen=True)
class Metric:
    subscription: str
    category: str
    kind: str
    value: float | None
    unit: str | None
    unlimited: bool = False
    default_allowance: float | None = None
    next_month_allowance: float | None = None
    maximum_limit: float | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.subscription, self.category, self.kind)


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and isfinite(value):
        return float(value)
    return None


def parse_usage(data: dict) -> dict[tuple[str, str, str], Metric]:
    usages = data.get("usages")
    if not isinstance(usages, list) or not usages:
        raise InvalidResponse("Usage response has no subscriptions")
    result = {}
    subscriptions = set()
    for usage in usages:
        if not isinstance(usage, dict) or not isinstance(usage.get("balances"), dict):
            raise InvalidResponse("Invalid subscription balances")
        # A single unnamed subscription has a stable account-local identity.
        identity = next(
            (
                usage[k]
                for k in ("subscriptionId", "id", "phoneNumber", "productKey")
                if isinstance(usage.get(k), (str, int)) and str(usage[k])
            ),
            None,
        )
        if identity is None and len(usages) != 1:
            raise InvalidResponse("Multiple subscriptions require stable identifiers")
        subscription = str(identity) if identity is not None else "primary"
        if subscription in subscriptions:
            raise InvalidResponse("Duplicate subscription identifiers")
        subscriptions.add(subscription)
        for category, raw in usage["balances"].items():
            if not isinstance(raw, dict) or not isinstance(raw.get("balance"), dict):
                continue
            balance = raw["balance"]
            used = number(raw.get("usage"))
            default_allowance = number(balance.get("value"))
            allowance = default_allowance
            # Custom current-month spending caps override the tariff default.
            if category.startswith("costLimit") and "customLimitCurrentMonth" in raw:
                allowance = number(raw["customLimitCurrentMonth"])
            next_month_allowance = number(raw.get("customLimitNextMonth"))
            unlimited = (
                balance.get("unlimited") is True or balance.get("value") == "unlimited"
            )
            unit = balance.get("unit", raw.get("unit"))
            if unit is None:
                unit_type = balance.get("unitType")
                if unit_type is not None and not isinstance(unit_type, str):
                    raise InvalidResponse("Invalid balance unit type")
                unit = {"GB": "GB", "MINUTE": "min", "SMS": "SMS"}.get(unit_type)
                if unit_type == "MONEY":
                    unit = balance.get("currencyCode", raw.get("currencyCode", "GBP"))
            # GB is specified in the supplied nationalData example only.
            if unit is None and category == "nationalData":
                unit = "GB"
            if unit is not None and (not isinstance(unit, str) or not unit.strip()):
                raise InvalidResponse("Invalid balance unit")
            if used is None and allowance is None and not unlimited:
                continue
            values = {
                "allowance": None if unlimited else allowance,
                "usage": used,
                "remaining": allowance - used
                if allowance is not None and used is not None and not unlimited
                else None,
            }
            for kind, value in values.items():
                metric = Metric(
                    subscription,
                    category,
                    kind,
                    value,
                    unit,
                    unlimited,
                    default_allowance,
                    next_month_allowance,
                    number(balance.get("maxValue")),
                )
                result[metric.key] = metric
    if not result:
        raise InvalidResponse("No supported balances in usage response")
    return result
