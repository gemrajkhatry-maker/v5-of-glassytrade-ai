from __future__ import annotations

def gate(can_trade: bool, cooldown_s: float, position_open: bool, qty: float) -> str | None:
    if not can_trade:
        return "HALTED"
    if cooldown_s > 0:
        return "COOLDOWN"
    if position_open:
        return "POSITION_OPEN"
    if qty <= 0:
        return "ZERO_SIZE"
    return None

def size(equity: float, risk_pct: float, entry: float, sl: float, lot: float = 1.0) -> float:
    risk_dist = abs(entry - sl)
    if risk_dist <= 0 or equity <= 0:
        return 0.0
    raw = (equity * risk_pct) / risk_dist
    lots = int(raw // max(1.0, lot))
    return float(max(0, lots) * max(1.0, lot))
