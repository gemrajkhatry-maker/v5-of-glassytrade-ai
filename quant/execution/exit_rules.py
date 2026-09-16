"""Pure exit rule functions. No state, no side effects.

These functions operate on Position objects and return exit decisions
or None. They are pure functions suitable for unit testing.
"""

from __future__ import annotations
from quant.contracts.enums import MarketState

import logging
from quant.contracts.enums import MarketStateCodec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session-aware time stop table (moved from exit_engine.py)
# ---------------------------------------------------------------------------

TIME_STOP_TABLE: dict[tuple[str, str], float] = {
    # Legacy generic phases
    ("MORNING", MarketState.BALANCED.value): 1200,
    ("MORNING", MarketState.IMBALANCED.value): 2700,
    ("AFTERNOON", MarketState.BALANCED.value): 900,
    ("AFTERNOON", MarketState.IMBALANCED.value): 1800,
    # Real session-phase names from get_session_info (NSE + MCX). Without
    # these the lookup ALWAYS missed and every stop fell back to static
    # 1800/7200 — the session-aware table was dead code.
    ("NSE_PRIMARY", MarketState.BALANCED.value): 1200,
    ("NSE_PRIMARY", MarketState.IMBALANCED.value): 2700,
    ("NSE_MIDDAY", MarketState.BALANCED.value): 900,
    ("NSE_MIDDAY", MarketState.IMBALANCED.value): 1800,
    ("NSE_POWER_HOUR", MarketState.BALANCED.value): 900,
    ("NSE_POWER_HOUR", MarketState.IMBALANCED.value): 1800,
    ("MCX_MORNING", MarketState.BALANCED.value): 1200,
    ("MCX_MORNING", MarketState.IMBALANCED.value): 2700,
    ("MCX_AFTERNOON", MarketState.BALANCED.value): 900,
    ("MCX_AFTERNOON", MarketState.IMBALANCED.value): 1800,
    ("MCX_EVENING", MarketState.BALANCED.value): 900,
    ("MCX_EVENING", MarketState.IMBALANCED.value): 1800,
}

EXPIRY_TIME_STOP: float = 600

# Hard ceiling: 120-minute absolute max hold for options scalping (Fabio Gap #3)
HARD_MAX_HOLD_SECONDS: float = 7200


# ---------------------------------------------------------------------------
# Exit Reasons (canonical source — imported by exit_engine.py)
# ---------------------------------------------------------------------------

class ExitReason:
    """Exit reason constants."""
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    TIME_STOP = "TIME_STOP"
    PARTIAL_TAKE_PROFIT = "PARTIAL_TAKE_PROFIT"
    SCRATCH = "SCRATCH"
    BREAK_EVEN = "BREAK_EVEN"
    OVERSEER_EXIT = "OVERSEER_EXIT"
    OVERSEER_PARTIAL = "OVERSEER_PARTIAL"
    SPREAD_BLOWOUT = "SPREAD_BLOWOUT"
    ADVERSE_EXIT = "ADVERSE_EXIT"  # Fabio: exit price < entry (loss before SL hit)


# ---------------------------------------------------------------------------
# Pure Exit Rule Functions
# ---------------------------------------------------------------------------


def classify_exit(
    direction: str,
    entry_price: float,
    exit_price: float,
    sl: float,
    tp: float,
    is_partial: bool = False,
    is_time_exit: bool = False,
    is_manual: bool = False,
) -> str:
    """Classify exit type per Fabio spec.

    Args:
        direction: "LONG" or "SHORT"
        entry_price: Entry price
        exit_price: Exit price
        sl: Stop loss price
        tp: Take profit price
        is_partial: Whether this is a partial exit
        is_time_exit: Whether this was a time stop
        is_manual: Whether this was manually triggered

    Returns:
        Exit reason string per Fabio classification.
    """
    is_long = direction == "LONG"

    # Check for take profit hits (must be before SL) - with tolerance for slippage
    tp_tolerance = max(abs(entry_price * 0.001), 0.5)  # 0.1% or 0.5 points tolerance
    if is_long and exit_price >= (tp - tp_tolerance):
        return ExitReason.TAKE_PROFIT
    if not is_long and exit_price <= (tp + tp_tolerance):
        return ExitReason.TAKE_PROFIT

    # Check for stop loss hits - with tolerance for slippage
    if is_long and exit_price <= (sl + tp_tolerance):
        return ExitReason.STOP_LOSS
    if not is_long and exit_price >= (sl - tp_tolerance):
        return ExitReason.STOP_LOSS

    # Adverse exit: exited below entry without hitting SL/TP
    if is_long and exit_price < entry_price and not is_manual:
        return ExitReason.ADVERSE_EXIT
    if not is_long and exit_price > entry_price and not is_manual:
        return ExitReason.ADVERSE_EXIT

    # Time partial
    if is_time_exit:
        return ExitReason.TIME_STOP

    # Partial profit
    if is_partial and exit_price > entry_price:
        return ExitReason.PARTIAL_TAKE_PROFIT

    # Manual exit
    if is_manual:
        return "MANUAL_EXIT"

    return ExitReason.SCRATCH


def get_session_time_stop(
    market_state: str,
    session_phase: str,
    is_expiry: bool,
    time_to_close: float,
) -> float:
    """Calculate session-aware time stop.

    Args:
        market_state: Market state (BALANCED/IMBALANCED).
        session_phase: Session phase (MORNING/AFTERNOON).
        is_expiry: Whether it's options expiry day.
        time_to_close: Seconds until market close.

    Returns:
        Time stop in seconds.
    """
    if is_expiry:
        phase_stop = EXPIRY_TIME_STOP
    elif session_phase:
        key = (session_phase.upper(), market_state.upper())
        phase_stop = TIME_STOP_TABLE.get(key, 0.0)
        if phase_stop == 0.0:
            phase_stop = 7200.0 if MarketStateCodec.is_imbalanced(market_state) else 1800.0
    else:
        phase_stop = 7200.0 if MarketStateCodec.is_imbalanced(market_state) else 1800.0

    if time_to_close > 0:
        near_close_stop = time_to_close - 300.0
        if near_close_stop > 0:
            phase_stop = min(phase_stop, near_close_stop)
        else:
            phase_stop = 1.0

    return phase_stop
