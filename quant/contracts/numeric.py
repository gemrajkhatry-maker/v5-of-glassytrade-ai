from __future__ import annotations
from typing import Any

def to_float(value: Any, default: float | None = 0.0) -> float | None:
    """Coerce a numeric (float/int/str/Decimal) to float, else `default`."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
