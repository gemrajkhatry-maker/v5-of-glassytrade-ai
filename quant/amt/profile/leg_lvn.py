"""Canonical resolution of impulse-leg LVN values from AMT DTOs."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LegLVNResolution:
    level: float = 0.0
    available: bool = False
    source: str = ""
    reason: str = "NO_LVN"


def resolve_leg_lvn(amt_dto: dict, close_px: float) -> LegLVNResolution:
    """Resolve the nearest positive LVN from the producer's ``legLvns`` list.

    ``legLvns`` is the only spelling the DTO emits; the singular ``legLvn``
    fallback this used to carry could never match, so a DTO without the plural
    list means "no leg LVN available" — not "try another key".
    """
    raw = (amt_dto or {}).get("legLvns")
    if not isinstance(raw, (list, tuple)):
        return LegLVNResolution()
    valid: list[float] = []
    for value in raw:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            valid.append(number)
    if not valid:
        return LegLVNResolution()
    level = min(valid, key=lambda value: abs(value - float(close_px)))
    return LegLVNResolution(level=level, available=True, source="legLvns", reason="")


def leg_lvn_retest_tolerance(tick_size: float, bucket_width: float, leg_range: float) -> float:
    """Bounded retest tolerance for a traceable LVN."""
    tick = max(float(tick_size or 0.0), 0.05)
    bucket = max(float(bucket_width or 0.0), tick)
    span = float(leg_range or 0.0)
    if span <= 0:
        return round(2.0 * tick, 10)
    return round(min(max(2.0 * tick, bucket), span * 0.25), 10)
