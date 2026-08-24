"""Initial Balance and structural value location."""

from __future__ import annotations

from decimal import Decimal


def location_for(close: Decimal, val: Decimal | None, vah: Decimal | None) -> str:
    if val is None or vah is None:
        return "UNKNOWN"
    if close < val:
        return "BELOW_VA"
    if close > vah:
        return "ABOVE_VA"
    return "INSIDE_VA"


def nearest_level(close: Decimal, *levels: Decimal | None) -> Decimal | None:
    available = [level for level in levels if level is not None]
    return min(available, key=lambda level: abs(level - close)) if available else None
