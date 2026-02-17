"""Pure quant functions for Fabio Playbook entry gates.

All functions are stateless and side-effect-free. They receive data
and return decisions — no threading, no events, no I/O.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.trading.models.enums import SignalType, Source, SetupType
from app.domain.trading.models.entities import Signal

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult, AggressivePrint

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Three-Align Gate
# ------------------------------------------------------------------

def three_align_check(
    data: list[OHLC],
    amt_result: AMTResult,
    tick: OHLC,
    order_book=None,
) -> bool:
    """Three-Align Gate: Market State + Location + Confirmation Bundle.

    All three conditions must pass before LLM fires.
    """
    if amt_result.poc <= 0 or amt_result.value_area_high <= 0 or amt_result.value_area_low <= 0:
        return False

    va_range = amt_result.value_area_high - amt_result.value_area_low
    state_ok = (
        amt_result.market_state in ("BALANCED", "IMBALANCED")
        and va_range > amt_result.poc * 0.001
    )
    if not state_ok:
        return False

    near_level = False
    threshold = tick.close * 0.003  # 0.3% — meaningful with proper VP lookback
    for level in [amt_result.value_area_high, amt_result.value_area_low, amt_result.poc]:
        if abs(tick.close - level) < threshold:
            near_level = True
            break
    if not near_level:
        for hvn in (amt_result.hvns or [])[:3]:
            if abs(tick.close - hvn) < threshold:
                near_level = True
                break
    if not near_level:
        for lvn in amt_result.lvns:
            if abs(tick.close - lvn) < threshold:
                near_level = True
                break

    agg_ok = check_confirmation_bundle(data, tick, order_book)
    return state_ok and near_level and agg_ok


# ------------------------------------------------------------------
# Confirmation Bundle
# ------------------------------------------------------------------

def check_confirmation_bundle(data: list[OHLC], tick: OHLC, order_book=None) -> bool:
    """Confirmation Bundle (2/3): Volume Impulse + Delta Pressure + Spread Tightness.

    Volume Impulse uses EMA(20) of volume (Valentini dynamic threshold).
    Spread Tightness: bid-ask spread must be <= 5 bps.
    """
    if not data or len(data) < 20:
        return False

    alpha = 2.0 / 21  # EMA(20)
    ema_vol = data[-20].volume
    for d in data[-19:]:
        ema_vol = alpha * d.volume + (1.0 - alpha) * ema_vol
    vol_impulse = tick.volume > (ema_vol * 1.5)

    delta_ratio = abs(tick.delta) / tick.volume if tick.volume > 0 else 0
    delta_pressure = delta_ratio > 0.15

    spread_tight = False
    if order_book and order_book.bids and order_book.asks:
        best_bid = order_book.bids[0].price
        best_ask = order_book.asks[0].price
        spread = best_ask - best_bid
        mid = (best_ask + best_bid) / 2
        if mid > 0:
            spread_bps = spread / mid * 10000
            spread_tight = spread_bps <= 5.0
    else:
        spread_tight = True

    score = sum([vol_impulse, delta_pressure, spread_tight])
    logger.debug("Confirmation bundle: vol_impulse=%s, delta_pressure=%s, spread_tight=%s -> %d/3",
                 vol_impulse, delta_pressure, spread_tight, score)
    return score >= 2


# ------------------------------------------------------------------
# Volatility Filter
# ------------------------------------------------------------------

def check_volatility_filter(data: list[OHLC], tick: OHLC) -> bool:
    """Returns True if entry should be BLOCKED due to extreme volatility or stale data."""
    if tick.volume <= 0:
        return True
    if len(data) >= 20:
        atr5 = sum(d.high - d.low for d in data[-5:]) / 5
        atr20 = sum(d.high - d.low for d in data[-20:]) / 20
        if atr20 > 0 and atr5 / atr20 > 3.0:
            return True
    return False


# ------------------------------------------------------------------
# ATR computation
# ------------------------------------------------------------------

def compute_atr(data: list[OHLC], period: int = 14) -> float:
    """Compute Average True Range over the last *period* bars."""
    if len(data) < period:
        return 0.0
    return sum(d.high - d.low for d in data[-period:]) / period


# ------------------------------------------------------------------
# Signal construction
# ------------------------------------------------------------------

def build_entry_signal(
    direction: str,
    tick: OHLC,
    amt_result: AMTResult,
    ai_result: dict,
    setup_type: SetupType = SetupType.TREND_MODEL,
) -> Signal:
    """Build Signal from LLM decision using Fabio Playbook SL/TP.

    Mean Reversion: TP at POC, tight SL beyond VA boundary.
    Trend Model:    TP extended beyond VA, wider SL, trailing allowed.
    VWAP used as tighter SL reference when available.
    """
    is_buy = direction == "LONG"
    sig_type = SignalType.BUY if is_buy else SignalType.SELL
    buffer = tick.close * 0.001
    vwap = amt_result.session_vwap if amt_result.session_vwap > 0 else (tick.vwap if tick.vwap > 0 else 0)

    agg_sl = sl_from_aggressive_print(amt_result, tick, is_buy, buffer)

    if setup_type == SetupType.MEAN_REVERSION:
        tp_price = amt_result.poc
        if is_buy:
            stop_price = agg_sl or (amt_result.value_area_low - buffer)
            if not agg_sl and vwap and stop_price < vwap < tick.close:
                stop_price = vwap - buffer
            if tp_price <= tick.close or stop_price >= tick.close:
                tp_price = tick.close * 1.010
                stop_price = tick.close * 0.995
        else:
            stop_price = agg_sl or (amt_result.value_area_high + buffer)
            if not agg_sl and vwap and stop_price > vwap > tick.close:
                stop_price = vwap + buffer
            if tp_price >= tick.close or stop_price <= tick.close:
                tp_price = tick.close * 0.990
                stop_price = tick.close * 1.005
        allow_trail = False
    else:
        if is_buy:
            tp_price = amt_result.value_area_high + (amt_result.value_area_high - amt_result.poc)
            stop_price = agg_sl or (amt_result.poc - buffer)
            if not agg_sl and vwap and stop_price < vwap < tick.close:
                stop_price = vwap - buffer
            if tp_price <= tick.close or stop_price >= tick.close:
                tp_price = tick.close * 1.020
                stop_price = tick.close * 0.990
        else:
            tp_price = amt_result.value_area_low - (amt_result.poc - amt_result.value_area_low)
            stop_price = agg_sl or (amt_result.poc + buffer)
            if not agg_sl and vwap and stop_price > vwap > tick.close:
                stop_price = vwap + buffer
            if tp_price >= tick.close or stop_price <= tick.close:
                tp_price = tick.close * 0.980
                stop_price = tick.close * 1.010
        allow_trail = True

    setup_label = "MeanRev" if setup_type == SetupType.MEAN_REVERSION else "Trend"

    return Signal(
        type=sig_type,
        price=tick.close,
        reason=f"LLM {setup_label}: {ai_result['rationale'][:80]}",
        setup=setup_type,
        source=Source.LLM,
        stop_loss=stop_price,
        take_profit=tp_price,
        timestamp=tick.time,
        metadata={
            "llm_entry": True,
            "allow_trail": allow_trail,
            "confidence": ai_result.get("confidence", "Medium"),
            "market_state_model": ai_result.get("market_state", "Unknown"),
            "raw_output": ai_result.get("raw_output", "")[:200],
        },
    )


def sl_from_aggressive_print(
    amt_result: AMTResult, tick: OHLC, is_buy: bool, buffer: float,
) -> float | None:
    """Fabio playbook: SL just beyond the aggressive print + buffer."""
    if not amt_result.aggressive_prints:
        return None
    proximity = tick.close * 0.005
    best = None
    for ap in amt_result.aggressive_prints[-5:]:
        if is_buy and ap.side == "SELL" and ap.price < tick.close:
            if abs(ap.price - tick.close) < proximity:
                if best is None or ap.price < best:
                    best = ap.price
        elif not is_buy and ap.side == "BUY" and ap.price > tick.close:
            if abs(ap.price - tick.close) < proximity:
                if best is None or ap.price > best:
                    best = ap.price
    if best is None:
        return None
    return (best - buffer) if is_buy else (best + buffer)
