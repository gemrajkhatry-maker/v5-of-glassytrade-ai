from __future__ import annotations
from quantv2.types import Context

def _triple_a(ctx: Context) -> str | None:
    x = ctx.extra
    if x.get("triple_phase") == "AGGRESSION" and x.get("triple_signal") in ("LONG", "SHORT") and x.get("acceptance"):
        return str(x["triple_signal"])
    return None

def _second_drive(ctx: Context) -> str | None:
    x = ctx.extra
    if x.get("is_second_drive") and x.get("rejection"):
        return str(x.get("direction") or ("SHORT" if x.get("rejection_high") else "LONG"))
    return None

def _lvn(ctx: Context) -> str | None:
    x = ctx.extra
    lvl = float(x.get("leg_lvn") or 0.0)
    if lvl > 0 and abs(ctx.bar.close - lvl) <= 2 * float(x.get("tick") or 0.05):
        if x.get("absorption") == "SELL_ABSORBED":
            return "LONG"
        if x.get("absorption") == "BUY_ABSORBED":
            return "SHORT"
    return None

def _initiative(ctx: Context) -> str | None:
    x = ctx.extra
    if x.get("break_type") == "INITIATIVE":
        return "LONG" if x.get("break_dir") == "UP" else ("SHORT" if x.get("break_dir") == "DOWN" else None)
    return None

def _squeeze(ctx: Context) -> str | None:
    x = ctx.extra
    if x.get("squeeze_dir") in ("LONG", "SHORT") and x.get("pullback"):
        return str(x["squeeze_dir"])
    return None

def _va_fade(ctx: Context) -> str | None:
    if ctx.val and ctx.bar.close < ctx.val and ctx.cvd_slope >= 0.2 and ctx.poc and ctx.bar.close < ctx.poc:
        return "LONG"
    if ctx.vah and ctx.bar.close > ctx.vah and ctx.cvd_slope <= -0.2 and ctx.poc and ctx.bar.close > ctx.poc:
        return "SHORT"
    return None

def detect(ctx: Context) -> tuple[str, str] | None:
    for name, fn in (("TRIPLE_A", _triple_a), ("SECOND_DRIVE", _second_drive), ("LVN_SNIPER", _lvn), ("INITIATIVE", _initiative), ("SQUEEZE", _squeeze), ("VA_FADE", _va_fade)):
        d = fn(ctx)
        if d in ("LONG", "SHORT"):
            return (name, d)
    return None
