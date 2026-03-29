"""Signal Generator — AMT signal construction from market state + aggression.

Extracted from amt_analyzer.py for SRP compliance.

Three playbooks:
  A. PROBING — unconfirmed break with high aggression (acceptance/rejection)
  B. Trend Continuation — IMBALANCED + LVN + aggression
  C. Mean Reversion — BALANCED + failed breakout + reclaim + aggression
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC


class MarketState(Enum):
    NO_TRADE = "NO_TRADE"
    BALANCED = "BALANCED"
    IMBALANCED = "IMBALANCED"
    PROBING = "PROBING"


def generate_signal(
    data: list[OHLC],
    current: OHLC,
    market_state: MarketState,
    has_aggression: bool,
    aggression_score: float,
    lvns: list[float],
    vah: float,
    val: float,
    poc: float,
    aggression_direction: int = 0,
    has_high_aggression: bool = False,
    session_vwap: float = 0.0,
    signal_cls=None,
    signal_type_cls=None,
    setup_type_cls=None,
    source_cls=None,
) -> object | None:
    """Generate direction signal from market microstructure.

    NOTE: SL/TP in this signal are PLACEHOLDERS (VA-based). The real SL/TP
    is computed by build_entry_signal() in entry_gate.py using the full
    Fabio playbook (aggressive print, VWAP, ATR floor, cushion override).
    This signal's only purpose: direction for fallback in LLM handler
    and serialization for UI display.

    Args:
        signal_cls: Signal class (injected to avoid circular import)
        signal_type_cls: SignalType enum
        setup_type_cls: SetupType enum
        source_cls: Source enum
    """
    if signal_cls is None:
        from app.domain.trading.models.entities import Signal as signal_cls
        from app.domain.trading.models.enums import SignalType as signal_type_cls
        from app.domain.trading.models.enums import SetupType as setup_type_cls
        from app.domain.trading.models.enums import Source as source_cls

    now_iso = current.time

    # GATE 3: NO_TRADE state never generates signals
    if market_state == MarketState.NO_TRADE:
        return None

    # C. PROBING Playbook — unconfirmed break with high aggression
    if market_state == MarketState.PROBING and has_high_aggression:
        above_vah = float(current.close) > vah
        below_val = float(current.close) < val
        above_vwap = float(current.close) > session_vwap if session_vwap > 0 else True
        below_vwap = float(current.close) < session_vwap if session_vwap > 0 else True

        if above_vah:
            if aggression_direction > 0 and above_vwap:
                return signal_cls(
                    type=signal_type_cls.BUY,
                    price=current.close,
                    reason="PROBING Acceptance: aggression confirms break above VAH (above VWAP)",
                    setup=setup_type_cls.TREND_MODEL,
                    source=source_cls.AMT,
                    stop_loss=val,
                    take_profit=vah + (vah - val),
                    timestamp=now_iso,
                )
            if aggression_direction < 0:
                return signal_cls(
                    type=signal_type_cls.SELL,
                    price=current.close,
                    reason="PROBING Rejection: opposing aggression at VAH (fade into value)",
                    setup=setup_type_cls.MEAN_REVERSION,
                    source=source_cls.AMT,
                    stop_loss=vah + (vah - val) * 0.25,
                    take_profit=poc,
                    timestamp=now_iso,
                )

        elif below_val:
            if aggression_direction < 0 and below_vwap:
                return signal_cls(
                    type=signal_type_cls.SELL,
                    price=current.close,
                    reason="PROBING Acceptance: aggression confirms break below VAL (below VWAP)",
                    setup=setup_type_cls.TREND_MODEL,
                    source=source_cls.AMT,
                    stop_loss=vah,
                    take_profit=val - (vah - val),
                    timestamp=now_iso,
                )
            if aggression_direction > 0:
                return signal_cls(
                    type=signal_type_cls.BUY,
                    price=current.close,
                    reason="PROBING Rejection: opposing aggression at VAL (fade into value)",
                    setup=setup_type_cls.MEAN_REVERSION,
                    source=source_cls.AMT,
                    stop_loss=val - (vah - val) * 0.25,
                    take_profit=poc,
                    timestamp=now_iso,
                )

    # A. Trend Continuation (Imbalanced + Pullback + LVN + Aggression)
    if market_state == MarketState.IMBALANCED and has_aggression:
        nearby_lvn = next(
            (lvn for lvn in lvns if abs(current.close - lvn) / lvn < 0.003),
            None,
        )

        if nearby_lvn:
            if current.close > poc and aggression_score > 0:
                return signal_cls(
                    type=signal_type_cls.BUY,
                    price=current.close,
                    reason="Trend Continuation: Aggression at LVN",
                    setup=setup_type_cls.TREND_MODEL,
                    source=source_cls.AMT,
                    stop_loss=val,
                    take_profit=poc,
                    timestamp=now_iso,
                )
            if current.close < poc and aggression_score < 0:
                return signal_cls(
                    type=signal_type_cls.SELL,
                    price=current.close,
                    reason="Trend Continuation: Aggression at LVN",
                    setup=setup_type_cls.TREND_MODEL,
                    source=source_cls.AMT,
                    stop_loss=vah,
                    take_profit=poc,
                    timestamp=now_iso,
                )

    # B. Mean Reversion (Balanced + Failed Breakout + Reclaim + Aggression)
    if market_state == MarketState.BALANCED and has_aggression and len(data) >= 5:
        recent = data[-10:]
        had_above = any(d.high > vah for d in recent[:-1])
        had_below = any(d.low < val for d in recent[:-1])
        is_inside = val <= current.close <= vah

        if is_inside:
            if had_below and aggression_score > 0 and current.close > val:
                return signal_cls(
                    type=signal_type_cls.BUY,
                    price=current.close,
                    reason="Mean Reversion: Confirmed Reclaim",
                    setup=setup_type_cls.MEAN_REVERSION,
                    source=source_cls.AMT,
                    stop_loss=val * 0.999,
                    take_profit=poc,
                    timestamp=now_iso,
                )
            if had_above and aggression_score < 0 and current.close < vah:
                return signal_cls(
                    type=signal_type_cls.SELL,
                    price=current.close,
                    reason="Mean Reversion: Confirmed Reclaim",
                    setup=setup_type_cls.MEAN_REVERSION,
                    source=source_cls.AMT,
                    stop_loss=vah * 1.001,
                    take_profit=poc,
                    timestamp=now_iso,
                )

    return None
