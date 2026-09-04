from __future__ import annotations
# ponytail: in-memory bar-close driver only; no persistence, no seeding
from quantv2.types import Bar, Context, Decision
from quantv2.pipeline import decide
from quantv2.oms import PaperOMS

def run_tape(records: list) -> dict:
    approved_without_position = 0
    for r in records:
        b = Bar(time=r["time"], open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r.get("volume", 0.0))
        ctx = Context(symbol=r.get("symbol", "X"), bar=b, vah=r.get("vah"), val=r.get("val"), poc=r.get("poc"), cvd_slope=r.get("cvd", 0.0), extra=r.get("extra", {}))
        d: Decision = decide(ctx, session_open=True, can_trade=True, cooldown_s=0.0, position_open=False, equity=100000.0, oms=PaperOMS())
        submitted = r.get("submitted", False)
        if d.approved and not submitted:
            approved_without_position += 1
    return {"approved_without_position": approved_without_position}
