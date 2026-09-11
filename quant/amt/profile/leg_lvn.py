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
    """Resolve the nearest positive LVN, preserving legacy DTO compatibility."""
    raw = (amt_dto or {}).get("legLvns")
    if isinstance(raw, (list, tuple)):
        valid: list[float] = []
        for value in raw:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number > 0:
                valid.append(number)
        if valid:
            level = min(valid, key=lambda value: abs(value - float(close_px)))
            return LegLVNResolution(level=level, available=True, source="legLvns", reason="")
    try:
        legacy = float((amt_dto or {}).get("legLvn") or 0.0)
    except (TypeError, ValueError):
        legacy = 0.0
    if legacy > 0:
        return LegLVNResolution(level=legacy, available=True, source="legLvn", reason="")
    return LegLVNResolution()
