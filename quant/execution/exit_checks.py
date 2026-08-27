"""Exit rule checks — individual exit conditions extracted from ExitEngine.evaluate().

Each function returns ExitDecision or None. The ExitEngine orchestrates them
in priority order; each rule is now independently testable and readable.
"""

from __future__ import annotations

from quant.contracts.enums import MarketState
from quant.execution.exits import ExitDecision
from quant.execution.order import Position


def check_spread_blowout(
    position: Position, close: float, best_bid: float | None, best_ask: float | None,
    is_expiry: bool, spread_max_pct: float,
) -> ExitDecision | None:
    """Rule 1: spread blowout — book is untradeable."""
    effective = (spread_max_pct * 0.5) if is_expiry else spread_max_pct
    if (best_bid is not None and best_ask is not None and close > 0
            and (best_ask - best_bid) / close >= effective):
        return ExitDecision(True, "SPREAD_BLOWOUT", (best_bid + best_ask) / 2)
    return None


def check_stop_loss(position: Position, low: float, high: float) -> ExitDecision | None:
    """Rule 2: hard stop-loss."""
    sl = float(position.order.signal.sl)
    long = position.size > 0
    if (long and low <= sl) or (not long and high >= sl):
        return ExitDecision(True, "SL", sl)
    return None


def check_cvd_kill(position: Position, dto: dict, cvd_kill_threshold: float) -> ExitDecision | None:
    """Rule 3: CVD kill — thesis invalidated by order flow."""
    slope = float(dto.get("cvdSlope") or 0.0)
    long = position.size > 0
    if (long and slope < -cvd_kill_threshold) or (not long and slope > cvd_kill_threshold):
        return ExitDecision(True, "CVD_KILL", 0.0)
    return None


def tp2_level(entry: float, tp: float) -> float:
    """Rule 4 second-tier target (tier>=1): entry ± 2×|tp−entry|.

    Side follows the profit direction of the signal: tp above entry uses
    long geometry (2R past entry, i.e. 1R past tp); tp below entry uses the
    short mirror — exactly matching check_take_profit_tiers' branches.
    Shared by the bar path and the tick path (position_manager).
    """
    r = abs(tp - entry)
    return entry + 2.0 * r if tp > entry else entry - 2.0 * r


def check_take_profit_tiers(
    position: Position, high: float, low: float, tp_tier: int, entry: float,
) -> tuple[ExitDecision | None, int]:
    """Rule 4: tiered take-profit (§13.3). Returns (decision, new_tier)."""
    tp = float(position.order.signal.tp)
    long = position.size > 0

    if tp_tier == 0:
        if (long and high >= tp) or (not long and low <= tp):
            return ExitDecision(True, "TP1", tp, partial_fraction=0.5), 1
    elif tp_tier == 1:
        tp2 = tp2_level(entry, tp)
        if (long and high >= tp2) or (not long and low <= tp2):
            return ExitDecision(True, "TP2", tp2, partial_fraction=0.5), 2
    return None, tp_tier


def check_trailing_stop(
    position: Position, close: float, low: float, high: float, sl: float,
    entry: float, risk: float, dto: dict, session_vwap: float,
    trail_giveback_pct: float, vwap_adverse_drift_pct: float,
    cvd_be_threshold: float, be_floor: float | None, trail_stop: float | None,
) -> tuple[ExitDecision | None, float | None, float | None]:
    """Rule 4b: trailing stop + breakeven. Returns (decision, new_be_floor, new_trail_stop)."""
    long = position.size > 0
    profit = (close - entry) if long else (entry - close)

    # CVD-based early breakeven
    if be_floor is None and profit > 0:
        cvd_slope = float(dto.get("cvdSlope") or 0.0)
        cvd_confirms = (
            (long and cvd_slope > cvd_be_threshold)
            or (not long and cvd_slope < -cvd_be_threshold)
        )
        if cvd_confirms:
            be_floor = entry

    # Standard 0.8R breakeven
    if be_floor is None and profit >= risk * 0.8:
        be_floor = entry

    # Trailing stop (armed at 1R)
    if profit >= risk:
        effective_giveback = trail_giveback_pct
        if session_vwap > 0 and entry > 0:
            vwap_drift = abs(close - session_vwap) / entry
            adverse = (long and close < session_vwap) or (not long and close > session_vwap)
            if adverse and vwap_drift > vwap_adverse_drift_pct:
                effective_giveback = trail_giveback_pct * 0.5

        candidate = (close - effective_giveback * profit if long
                     else close + effective_giveback * profit)
        candidate = max(candidate, sl) if long else min(candidate, sl)
        if be_floor is not None:
            candidate = max(candidate, be_floor) if long else min(candidate, be_floor)

        if trail_stop is None:
            trail_stop = candidate
        else:
            trail_stop = max(trail_stop, candidate) if long else min(trail_stop, candidate)

    # VWAP adverse-drift early exit
    if 0 < profit < risk and session_vwap > 0 and entry > 0:
        vwap_drift = abs(close - session_vwap) / entry
        adverse = (long and close < session_vwap) or (not long and close > session_vwap)
        if adverse and vwap_drift > 2.0 * vwap_adverse_drift_pct:
            return ExitDecision(True, "VWAP_DRIFT", close), be_floor, trail_stop

    # Breakeven stop
    if be_floor is not None and trail_stop is None:
        if (long and low <= be_floor) or (not long and high >= be_floor):
            return ExitDecision(True, "BREAKEVEN", close), be_floor, trail_stop

    # Trail stop hit
    if trail_stop is not None:
        if (long and low <= trail_stop) or (not long and high >= trail_stop):
            return ExitDecision(True, "TRAIL", close, trail_stop=trail_stop), be_floor, trail_stop

    return None, be_floor, trail_stop


def check_time_stop(
    bar_index: int, time_stop_bars: int, session_phase: str, time_to_close: float,
    now_epoch: float, entry_time_epoch: float, market_state: MarketState, is_expiry: bool,
) -> ExitDecision | None:
    """Rule 5: time stop — session-aware or bar-count based."""
    from quant.execution.exit_rules import get_session_time_stop
    if session_phase and time_to_close > 0 and now_epoch and entry_time_epoch:
        max_hold = get_session_time_stop(market_state, session_phase, is_expiry, time_to_close)
        if now_epoch - entry_time_epoch >= max_hold:
            return ExitDecision(True, "TIME", 0.0)
    elif bar_index >= time_stop_bars:
        return ExitDecision(True, "TIME", 0.0)
    return None
