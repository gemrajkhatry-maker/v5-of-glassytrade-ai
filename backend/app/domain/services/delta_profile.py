"""Domain helpers for delta-profile analytics."""

from __future__ import annotations

from app.domain.constants import DELTA_ZONE_SIGMA_MULT


def detect_high_delta_zones(
    buckets: dict[float, list[int]],
    direction: str,
    sigma_mult: float = DELTA_ZONE_SIGMA_MULT,
) -> list[float]:
    """Detect high delta zones for LONG/SHORT entry candidates."""
    if not buckets:
        return []

    net_deltas = [abs(values[2]) for values in buckets.values() if values[3] > 0]
    if not net_deltas:
        return []

    mean_abs = sum(net_deltas) / len(net_deltas)
    threshold = mean_abs * sigma_mult

    zones: list[float] = []
    for price, values in buckets.items():
        net = values[2]
        if direction == "LONG" and net < -threshold:
            zones.append(price)
        elif direction == "SHORT" and net > threshold:
            zones.append(price)

    return sorted(zones)
