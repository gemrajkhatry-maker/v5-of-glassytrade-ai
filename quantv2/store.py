from __future__ import annotations
import json
from dataclasses import asdict
from quantv2.oms import Position


def save(coordinator, path: str) -> None:
    data = {}
    for symbol, eng in coordinator.engines.items():
        data[symbol] = {
            "position": asdict(eng.position) if eng.position is not None else None,
            "open_risk": eng.open_risk,
            "trail": eng.trail,
        }
    with open(path, "w") as f:
        json.dump(data, f)


def restore(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}
