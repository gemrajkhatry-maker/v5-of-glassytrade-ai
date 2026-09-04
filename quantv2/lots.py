from __future__ import annotations
import json

def load_lots(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}

def lot_of(registry: dict, symbol: str, default_lot: float = 1.0, default_tick: float = 0.05) -> tuple[float, float]:
    e = registry.get(symbol) or {}
    lot = float(e.get("lot_size") or default_lot)
    tick = float(e.get("tick_size") or default_tick)
    return (max(1.0, lot), max(0.0001, tick))
