from __future__ import annotations
from dataclasses import dataclass
from quantv2.types import Bar
from quantv2.oms import Position

@dataclass(frozen=True)
class ExitConfig:
    time_stop_min: int = 60
    trail_ticks: int = 4
    tick: float = 0.05
    session_close_ts: str = ""

@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason: str
    price: float

def _breakeven_triggered(side: str, entry: float, peak: float, risk: float) -> bool:
    return (peak - entry) >= risk if side == "LONG" else (entry - peak) >= risk

def evaluate_exit(pos: Position, bar: Bar, trail: dict, cfg: ExitConfig, elapsed_min: float | None = None) -> tuple[ExitDecision, dict]:
    tick = cfg.tick if cfg.tick > 0 else 0.05
    prev_peak = float(trail.get("peak", pos.entry))
    prev_be = bool(trail.get("be", False))
    risk = abs(pos.entry - pos.sl)
    prev_floor = pos.entry if prev_be else None
    if pos.side == "LONG":
        stop = max(pos.sl, prev_floor) if prev_floor is not None else pos.sl
    else:
        stop = min(pos.sl, prev_floor) if prev_floor is not None else pos.sl
    peak = max(prev_peak, bar.high) if pos.side == "LONG" else min(prev_peak, bar.low)
    if elapsed_min is not None and cfg.time_stop_min > 0 and elapsed_min >= cfg.time_stop_min:
        return ExitDecision(True, "TIME_STOP", bar.close), {"peak": peak, "be": prev_be}
    # Evaluate against prior-bar trailing state; the current bar only
    # arms/updates peak + breakeven for subsequent bars (it cannot stop
    # itself out on a level it just established intrabar).
    decision: ExitDecision | None = None
    if pos.side == "LONG":
        if bar.low <= stop:
            decision = ExitDecision(True, "BREAKEVEN" if prev_be and stop == pos.entry else "STOP_LOSS", stop)
        elif bar.high >= pos.tp:
            decision = ExitDecision(True, "TAKE_PROFIT", pos.tp)
        elif prev_peak - cfg.trail_ticks * tick >= pos.entry and bar.low <= prev_peak - cfg.trail_ticks * tick:
            decision = ExitDecision(True, "TRAIL", prev_peak - cfg.trail_ticks * tick)
    else:
        if bar.high >= stop:
            decision = ExitDecision(True, "BREAKEVEN" if prev_be and stop == pos.entry else "STOP_LOSS", stop)
        elif bar.low <= pos.tp:
            decision = ExitDecision(True, "TAKE_PROFIT", pos.tp)
        elif prev_peak + cfg.trail_ticks * tick <= pos.entry and bar.high >= prev_peak + cfg.trail_ticks * tick:
            decision = ExitDecision(True, "TRAIL", prev_peak + cfg.trail_ticks * tick)
    if decision is None and cfg.session_close_ts and bar.time >= cfg.session_close_ts:
        decision = ExitDecision(True, "SESSION_CLOSE", bar.close)
    be = prev_be or (risk > 0 and _breakeven_triggered(pos.side, pos.entry, peak, risk))
    state = {"peak": peak, "be": be}
    if decision is None:
        decision = ExitDecision(False, "HOLD", bar.close)
    return decision, state
