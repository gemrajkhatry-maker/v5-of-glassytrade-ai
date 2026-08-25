"""Pure exit rule functions. No state, no side effects.

These functions operate on Position objects and return exit decisions
or None. They are pure functions suitable for unit testing.
"""

from __future__ import annotations
from quant.contracts.enums import MarketState

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from quant.contracts.enums import CushionState, MarketStateCodec, Side
from quant.contracts.constants import MIN_RR_RATIO

if TYPE_CHECKING:
    from quant.contracts.entities import Position

from quant.execution.exit_signal import ExitSignal

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


def check_stop_loss(
    position: "Position",
    current_price: float,
    stop_price: float | None = None,
) -> "ExitSignal | None":
    """Check if position's hard stop loss has been hit.

    Args:
        position: Position to check.
        current_price: Current market price.
        stop_price: Optional stop price to check against (defaults to current_price).

    Returns:
        ExitSignal if stop loss hit, None otherwise.
    """
    is_long = position.side == Side.LONG or position.side.value == "LONG"
    sl = float(position.stop_loss)
    sl_check = stop_price if stop_price is not None else current_price

    if is_long and sl_check <= sl:
        logger.info(
            "ExitRules: STOP LOSS hit for %s at %.2f", position.id, current_price
        )
        position.advance_cushion_state(CushionState.CLOSED)
        return ExitSignal(position.id, ExitReason.STOP_LOSS, current_price)

    if not is_long and sl_check >= sl:
        logger.info(
            "ExitRules: STOP LOSS hit for %s at %.2f", position.id, current_price
        )
        position.advance_cushion_state(CushionState.CLOSED)
        return ExitSignal(position.id, ExitReason.STOP_LOSS, current_price)

    return None


def check_time_stop(
    position: "Position",
    current_time: float,
    time_to_close: float,
    max_hold_seconds: float,
    scratch_threshold_pct: float,
) -> "ExitSignal | None":
    """Check session-aware time stop.

    Args:
        position: Position to check.
        current_time: Current monotonic time (epoch seconds).
        time_to_close: Seconds until market close.
        max_hold_seconds: Default max hold time from config.
        scratch_threshold_pct: Threshold for scratch exit (minimal movement).

    Returns:
        ExitSignal if time stop or scratch triggered, None otherwise.
    """
    # Resolve entry_time: Position stores it as ISO string
    entry_time_epoch: float
    if position.entry_time:
        try:
            dt = datetime.fromisoformat(position.entry_time)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            entry_time_epoch = dt.timestamp()
        except (ValueError, TypeError):
            entry_time_epoch = current_time  # fallback: no time stop
    else:
        entry_time_epoch = current_time

    # Derive market_state from position metadata
    market_state = MarketState.BALANCED
    if position.metadata:
        ms = position.metadata.get("market_state_model", "")
        if ms and ("trend" in str(ms).lower() or "imbalance" in str(ms).lower()):
            market_state = MarketState.IMBALANCED

    if position.session_phase or position.is_expiry:
        new_stop = get_session_time_stop(
            market_state=market_state,
            session_phase=position.session_phase,
            is_expiry=position.is_expiry,
            time_to_close=time_to_close,
        )
        position.applied_time_stop = max(position.applied_time_stop, new_stop)
        max_hold = position.applied_time_stop
    else:
        max_hold = max_hold_seconds
        if MarketStateCodec.is_imbalanced(market_state):
            max_hold = 7200

    # Hard ceiling: never exceed 120 minutes regardless of market state
    max_hold = min(max_hold, HARD_MAX_HOLD_SECONDS)

    if (current_time - entry_time_epoch) >= max_hold:
        entry_price = float(position.entry_price)
        price_move_pct = (
            abs(current_time - entry_price) / entry_price if entry_price else 0.0
        )
        # Note: We need current_price here, but we don't have it. 
        # This is a limitation - caller should pass current_price.
        # For now, use a placeholder - this will be fixed in the refactored ExitEngine.
        price_move_pct = 0.0  # Will be computed properly in ExitEngine

        if price_move_pct < scratch_threshold_pct:
            logger.info(
                "ExitRules: SCRATCH for %s after %.0fs (move=%.5f)",
                position.id,
                current_time - entry_time_epoch,
                price_move_pct,
            )
            position.advance_cushion_state(CushionState.CLOSED)
            return ExitSignal(position.id, ExitReason.SCRATCH, 0.0)  # Price set by caller

        logger.info(
            "ExitRules: TIME STOP for %s after %.0fs",
            position.id,
            current_time - entry_time_epoch,
        )
        position.advance_cushion_state(CushionState.CLOSED)
        return ExitSignal(position.id, ExitReason.TIME_STOP, 0.0)  # Price set by caller

    return None


def check_time_stop_with_price(
    position: "Position",
    current_price: float,
    current_time: float,
    time_to_close: float,
    max_hold_seconds: float,
    scratch_threshold_pct: float,
) -> "ExitSignal | None":
    """Check session-aware time stop with current price.

    This is the preferred version that takes current_price directly.

    Args:
        position: Position to check.
        current_price: Current market price.
        current_time: Current monotonic time (epoch seconds).
        time_to_close: Seconds until market close.
        max_hold_seconds: Default max hold time from config.
        scratch_threshold_pct: Threshold for scratch exit (minimal movement).

    Returns:
        ExitSignal if time stop or scratch triggered, None otherwise.
    """
    # Resolve entry_time: Position stores it as ISO string
    entry_time_epoch: float
    if position.entry_time:
        try:
            dt = datetime.fromisoformat(position.entry_time)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            entry_time_epoch = dt.timestamp()
        except (ValueError, TypeError):
            entry_time_epoch = current_time  # fallback: no time stop
    else:
        entry_time_epoch = current_time

    # Derive market_state from position metadata
    market_state = MarketState.BALANCED
    if position.metadata:
        ms = position.metadata.get("market_state_model", "")
        if ms and ("trend" in str(ms).lower() or "imbalance" in str(ms).lower()):
            market_state = MarketState.IMBALANCED

    if position.session_phase or position.is_expiry:
        new_stop = get_session_time_stop(
            market_state=market_state,
            session_phase=position.session_phase,
            is_expiry=position.is_expiry,
            time_to_close=time_to_close,
        )
        position.applied_time_stop = max(position.applied_time_stop, new_stop)
        max_hold = position.applied_time_stop
    else:
        max_hold = max_hold_seconds
        if MarketStateCodec.is_imbalanced(market_state):
            max_hold = 7200

    # Hard ceiling: never exceed 120 minutes regardless of market state
    max_hold = min(max_hold, HARD_MAX_HOLD_SECONDS)

    if (current_time - entry_time_epoch) >= max_hold:
        entry_price = float(position.entry_price)
        sl = float(position.stop_loss or position.initial_stop or 0)
        tp = float(position.take_profit or 0)
        
        # Calculate R-multiple (profit relative to risk)
        is_long = position.side.value == "LONG" if hasattr(position.side, "value") else str(position.side) == "LONG"
        risk_per_unit = abs(entry_price - sl) if sl else 0
        profit_per_unit = current_price - entry_price if is_long else entry_price - current_price
        r_multiple = (profit_per_unit / risk_per_unit) if risk_per_unit > 0 else 0
        
        # R-MULTIPLE CHECK: Don't exit if ≥ 1R, activate trailing instead
        if r_multiple >= 1.0:
            # Do NOT force-exit a winner at time stop — trailing/partition
            # logic owns the exit from here.  Protect the locked profit: ensure
            # the stop sits at least at breakeven (never loosens an already
            # trailed stop), and extend the hold window so a re-check on the
            # next tick doesn't kill the runner prematurely.
            if not position.breakeven_set:
                position.breakeven_set = True
                if is_long and position.stop_loss < position.entry_price:
                    position.stop_loss = position.entry_price
                elif not is_long and position.stop_loss > position.entry_price:
                    position.stop_loss = position.entry_price
            position.applied_time_stop = max(
                position.applied_time_stop, int(max_hold * 1.3)
            )
            logger.info(
                "TIME_STOP: Holding winner %s - %.2fR (>= 1R), "
                "trailing/partitions manage the exit",
                position.id,
                r_multiple,
            )
            return None
        
        # 0.5R to 1R: Move SL to breakeven, give more time
        if 0.5 <= r_multiple < 1.0:
            logger.info(
                "TIME_STOP: Breakeven for %s - R-multiple=%.2fR (0.5R-1R)",
                position.id,
                r_multiple,
            )
            position.stop_loss = position.entry_price  # Move to breakeven
            position.breakeven_set = True
            # Extend hold time by 30% for this case
            position.applied_time_stop = int(max_hold * 1.3)
            return None
        
        # Negative P&L: Exit with warning
        if r_multiple < 0:
            logger.warning(
                "TIME_STOP: SL NOT TRIGGERED BUG for %s - negative P&L at TIME_STOP",
                position.id,
            )
        
        # 0 to 0.5R: Exit immediately
        price_move_pct = (
            abs(current_price - entry_price) / entry_price if entry_price else 0.0
        )

        if price_move_pct < scratch_threshold_pct:
            logger.info(
                "ExitRules: SCRATCH for %s after %.0fs (move=%.5f)",
                position.id,
                current_time - entry_time_epoch,
                price_move_pct,
            )
            position.advance_cushion_state(CushionState.CLOSED)
            return ExitSignal(position.id, ExitReason.SCRATCH, current_price)

        logger.info(
            "ExitRules: TIME STOP for %s after %.0fs",
            position.id,
            current_time - entry_time_epoch,
        )
        position.advance_cushion_state(CushionState.CLOSED)
        return ExitSignal(position.id, ExitReason.TIME_STOP, current_price)

    return None


def check_scratch(
    position: "Position",
    current_price: float,
    current_time: float,
    max_hold_seconds: float,
    scratch_threshold_pct: float,
) -> "ExitSignal | None":
    """Check scratch exit (minimal movement after time threshold).

    A scratch exit is triggered when the position has been held for
    the max hold time but has not moved significantly.

    Args:
        position: Position to check.
        current_price: Current market price.
        current_time: Current monotonic time (epoch seconds).
        max_hold_seconds: Max hold time threshold.
        scratch_threshold_pct: Minimum price movement to avoid scratch.

    Returns:
        ExitSignal if scratch triggered, None otherwise.
    """
    # Resolve entry_time: Position stores it as ISO string
    entry_time_epoch: float
    if position.entry_time:
        try:
            dt = datetime.fromisoformat(position.entry_time)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            entry_time_epoch = dt.timestamp()
        except (ValueError, TypeError):
            return None
    else:
        return None

    if (current_time - entry_time_epoch) < max_hold_seconds:
        return None

    entry_price = float(position.entry_price)
    price_move_pct = (
        abs(current_price - entry_price) / entry_price if entry_price else 0.0
    )

    if price_move_pct < scratch_threshold_pct:
        logger.info(
            "ExitRules: SCRATCH for %s after %.0fs (move=%.5f)",
            position.id,
            current_time - entry_time_epoch,
            price_move_pct,
        )
        position.advance_cushion_state(CushionState.CLOSED)
        return ExitSignal(position.id, ExitReason.SCRATCH, current_price)

    return None


def update_excursions(position: "Position", current_price: float) -> None:
    """Update MAE/MFE/peak_profit tracking on Position.

    MAE (Maximum Adverse Excursion): Largest unrealized loss from entry.
    MFE (Maximum Favorable Excursion): Largest unrealized gain from entry.

    Args:
        position: Position to update.
        current_price: Current market price.
    """
    is_long = position.side == Side.LONG or position.side.value == "LONG"
    entry_price = float(position.entry_price)

    unrealised = (
        (current_price - entry_price) if is_long else (entry_price - current_price)
    )

    mfe = float(position.mfe)
    mae = float(position.mae)

    if unrealised > mfe:
        position.mfe = Decimal(str(unrealised))

    if unrealised < -mae:
        position.mae = Decimal(str(-unrealised))


def update_peak_profit(position: "Position", current_price: float) -> float:
    """Update peak profit tracking and return the current peak.

    Args:
        position: Position to update.
        current_price: Current market price.

    Returns:
        The updated peak profit value.
    """
    is_long = position.side == Side.LONG or position.side.value == "LONG"
    entry_price = float(position.entry_price)

    unrealised = (
        (current_price - entry_price) if is_long else (entry_price - current_price)
    )

    peak_profit = float(position.peak_profit)
    if unrealised > peak_profit:
        position.peak_profit = Decimal(str(unrealised))
        peak_profit = unrealised

    return peak_profit


def check_spread_blowout(
    position: "Position",
    best_bid: float,
    best_ask: float,
    premium: float,
    max_spread_pct: float = 0.03,
) -> "ExitSignal | None":
    """Check for spread blowout and return exit signal if triggered.

    Spread >= max_spread_pct of premium triggers exit.

    Args:
        position: Position to check.
        best_bid: Current best bid price.
        best_ask: Current best ask price.
        premium: Option premium for spread calculation.
        max_spread_pct: Maximum allowed spread as fraction of premium.

    Returns:
        ExitSignal if spread blowout detected, None otherwise.
    """

    if best_bid <= 0 or best_ask <= 0 or premium <= 0:
        return None

    spread = best_ask - best_bid
    spread_pct = spread / premium

    if spread_pct >= max_spread_pct:
        logger.info(
            "ExitRules: SPREAD BLOWOUT for %s — spread=%.2f (%.1f%% of premium %.2f)",
            position.id, spread, spread_pct * 100, premium,
        )
        exit_price = (best_bid + best_ask) / 2
        position.advance_cushion_state(CushionState.CLOSED)
        return ExitSignal(position.id, ExitReason.SPREAD_BLOWOUT, exit_price)

    return None


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


def is_valid_rr(
    entry: float, sl: float, tp: float, min_rr: float | None = None
) -> bool:
    """Validate risk-reward ratio.

    Args:
        entry: Entry price.
        sl: Stop loss price.
        tp: Take profit price.
        min_rr: Minimum required RR ratio (default from constants).

    Returns:
        True if RR ratio meets minimum threshold.
    """

    threshold = min_rr if min_rr is not None else MIN_RR_RATIO
    if entry <= 0:
        return False
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 0 or reward <= 0:
        return False
    return (reward / risk) >= threshold
