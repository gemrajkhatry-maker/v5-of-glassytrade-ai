from __future__ import annotations


def snapshot(coordinator) -> dict:
    out = {}
    for symbol, eng in coordinator.engines.items():
        out[symbol] = {
            "position": eng.position,
            "last_decision": getattr(eng, "last_decision", None),
            "open_risk": eng.open_risk,
        }
    return out
