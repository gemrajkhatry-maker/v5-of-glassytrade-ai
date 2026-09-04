from __future__ import annotations
# ponytail: in-memory bar-close driver only; no persistence, no seeding
from quantv2.types import Bar, Context, Decision
from quantv2.pipeline import decide
from quantv2.oms import PaperOMS

def run_tape(records: list, oms=None) -> dict:
    oms = oms or PaperOMS()
    approvals = 0
    phantoms = 0
    min_rr = float("inf")
    monotonic_ok = True
    for r in records:
        b = Bar(time=r["time"], open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r.get("volume", 0.0))
        ctx = Context(symbol=r.get("symbol", "X"), bar=b, tick=r.get("tick", 0.05), vah=r.get("vah"), val=r.get("val"), poc=r.get("poc"), cvd_slope=r.get("cvd", 0.0), extra=r.get("extra", {}))
        d: Decision = decide(ctx, session_open=True, can_trade=True, cooldown_s=0.0, position_open=False, equity=100000.0, oms=oms)
        if d.approved and d.signal is not None:
            approvals += 1
            if not r.get("submitted", False):
                phantoms += 1
            min_rr = min(min_rr, d.signal.rr)
            s = d.signal
            ok = (s.sl < s.entry < s.tp) if s.type == "LONG" else (s.sl > s.entry > s.tp)
            monotonic_ok = monotonic_ok and ok
    return {"approvals": approvals, "approved_without_position": phantoms, "phantoms": phantoms, "min_rr": min_rr, "monotonic_ok": monotonic_ok}

def compare_tapes(v1_setup_hits: int, v2_approvals: int) -> bool:
    return v2_approvals <= v1_setup_hits
