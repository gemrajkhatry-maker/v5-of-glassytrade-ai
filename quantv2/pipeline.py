from __future__ import annotations
from quantv2.types import Context, Decision
from quantv2.setups import detect
from quantv2.stops import build_signal
from quantv2.risk import gate, size

def decide(ctx: Context, *, session_open: bool, can_trade: bool, cooldown_s: float, position_open: bool, equity: float, risk_pct: float = 0.005, lot: float = 1.0, tick: float = 0.05) -> Decision:
    if not session_open:
        return Decision(False, "SESSION_CLOSED")
    if not can_trade:
        return Decision(False, "HALTED")
    if cooldown_s > 0:
        return Decision(False, "COOLDOWN")
    if position_open:
        return Decision(False, "POSITION_OPEN")
    hit = detect(ctx)
    if hit is None:
        return Decision(False, "NO_EDGE")
    setup, direction = hit
    sig = build_signal(ctx, direction, setup, tick=tick)
    if sig is None:
        return Decision(False, "NO_STRUCTURE")
    qty = size(equity, risk_pct, sig.entry, sig.sl, lot)
    blocked = gate(can_trade, cooldown_s, position_open, qty)
    if blocked is not None:
        return Decision(False, blocked)
    return Decision(True, setup, sig)
