"""Signal Generator — produces trade signals from AMT analysis.

SL/TP derived from aggressive prints and LVN/HVN zones, NOT fixed points.
"""

from __future__ import annotations

import time
import logging
from appv2.domain.models.signal import Signal
from appv2.domain.enums.signal_type import SignalType, SetupType
from appv2.config import constants as C

logger = logging.getLogger(__name__)


def build_signal(
    symbol: str,
    underlying: str,
    direction: str,  # "LONG" or "SHORT"
    setup_type: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    confidence: float,
    market_state: str,
    session_phase: str,
    poc: float = 0.0,
    vah: float = 0.0,
    val: float = 0.0,
    vwap: float = 0.0,
    aggression_score: float = 0.0,
    drive_number: int = 0,
    strike_price: float = 0.0,
    option_type: str = "",
    expiry_date: str = "",
    delta: float = 0.0,
    theta: float = 0.0,
    gates_passed: str = "",
    gate_rejections: str = "",
    tick_size: float = 0.05,
) -> Signal | None:
    """Build a signal with validation.

    Returns None if R:R < minimum or SL is unreasonable.
    """
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)

    # Guard: minimum R:R
    if risk > 0 and reward / risk < C.GATE_SOFT_MIN_RR:
        logger.warning(
            "Signal rejected: R:R %.2f < %.1f for %s %s",
            reward / risk, C.GATE_SOFT_MIN_RR, symbol, direction,
        )
        return None

    # Guard: SL must be at least 1 tick away
    if risk < tick_size:
        logger.warning("Signal rejected: SL too tight (%.4f) for %s", risk, symbol)
        return None

    return Signal(
        symbol=symbol,
        underlying_symbol=underlying,
        direction=SignalType(direction),
        setup_type=SetupType(setup_type),
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        confidence=min(1.0, max(0.0, confidence)),
        market_state=market_state,
        session_phase=session_phase,
        timestamp=time.time(),
        ttl_seconds=C.SIGNAL_TTL_SECONDS,
        poc=poc,
        vah=vah,
        val=val,
        vwap=vwap,
        aggression_score=aggression_score,
        drive_number=drive_number,
        strike_price=strike_price,
        option_type=option_type,
        expiry_date=expiry_date,
        delta=delta,
        theta=theta,
        gates_passed=gates_passed,
        gate_rejections=gate_rejections,
    )


def compute_sl_from_aggressive_print(
    direction: str,
    entry_price: float,
    aggressive_level: float,
    tick_size: float,
    buffer_ticks: int = 3,
) -> float:
    """Compute SL from nearest aggressive print level.

    LONG: SL = aggressive_level - buffer_ticks × tick_size
    SHORT: SL = aggressive_level + buffer_ticks × tick_size
    """
    buffer = buffer_ticks * tick_size
    if direction == "LONG":
        return aggressive_level - buffer
    return aggressive_level + buffer


def compute_tp_from_vah_val(
    direction: str,
    entry_price: float,
    stop_loss: float,
    vah: float,
    val: float,
    rr_ratio: float = 1.5,
) -> float:
    """Compute TP based on VAH/VAL target with R:R ratio.

    LONG: TP = min(VAH, entry + risk × RR)
    SHORT: TP = max(VAL, entry - risk × RR)
    """
    risk = abs(entry_price - stop_loss)
    if risk <= 0:
        return entry_price  # No risk defined

    if direction == "LONG":
        rr_target = entry_price + risk * rr_ratio
        if vah > entry_price:
            return min(vah, rr_target)
        return rr_target
    else:  # SHORT
        rr_target = entry_price - risk * rr_ratio
        if val < entry_price:
            return max(val, rr_target)
        return rr_target
