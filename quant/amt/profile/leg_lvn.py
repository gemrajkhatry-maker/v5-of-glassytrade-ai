"""Canonical resolution of impulse-leg LVN values from AMT DTOs."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LegLVNResolution:
    level: float = 0.0
    available: bool = False
    source: str = ""
    reason: str = "NO_LVN"


def _leg_lvn_levels(src) -> tuple[list[float], str]:
    if hasattr(src, "result"):
        levels = list(getattr(src.result, "leg_lvns", None) or ())
        return levels, "leg_lvns"
    if hasattr(src, "leg_lvns"):
        return list(getattr(src, "leg_lvns", None) or ()), "leg_lvns"
    raw = (src or {}).get("legLvns") if isinstance(src, dict) else None
    if not isinstance(raw, (list, tuple)):
        return [], ""
    return list(raw), "legLvns"


def resolve_leg_lvn(src, close_px: float) -> LegLVNResolution:
    """Resolve the nearest positive LVN from typed ``leg_lvns`` or WS ``legLvns``.

    ``legLvns`` is the only spelling the DTO emits; the singular ``legLvn``
    fallback this used to carry could never match, so a DTO without the plural
    list means "no leg LVN available" — not "try another key".
    """
    levels, source_key = _leg_lvn_levels(src)
    if not levels:
        return LegLVNResolution()
    valid: list[float] = []
    for value in levels:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            valid.append(number)
    if not valid:
        return LegLVNResolution()
    level = min(valid, key=lambda value: abs(value - float(close_px)))
    return LegLVNResolution(level=level, available=True, source=source_key, reason="")


def leg_lvn_retest_tolerance(tick_size: float, bucket_width: float, leg_range: float) -> float:
    """Bounded retest tolerance for a traceable LVN."""
    tick = max(float(tick_size or 0.0), 0.05)
    bucket = max(float(bucket_width or 0.0), tick)
    span = float(leg_range or 0.0)
    if span <= 0:
        return round(2.0 * tick, 10)
    return round(min(max(2.0 * tick, bucket), span * 0.25), 10)
