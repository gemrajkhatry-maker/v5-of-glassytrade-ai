"""Build execution signals from AMT + gate context."""

from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING

from app.domain.services.tick_utils import round_down_to_tick, round_up_to_tick
from app.domain.trading.model.enums import SetupType, SignalType, Source
from app.domain.trading.model.entities import Signal
from app.domain.amt.service.entry_gates import calculate_position_size as _legacy_size
from app.domain.amt.service.trade_thesis import build_trade_thesis
from app.domain.fabio_ai.services.entry_gates.grading import compute_grade_score
from app.domain.fabio_ai.services.entry_gates.confirmation_bundle import compute_atr

if TYPE_CHECKING:
    from app.domain.trading.model.value_objects import AMTResult, OHLC


def _to_float(value, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def sl_from_aggressive_print(
    amt_result: "AMTResult",
    tick: "OHLC",
    is_buy: bool,
    buffer: float,
    inside_cluster: bool = False,
) -> float | None:
    """Priority SL beyond nearest opposing aggressive print."""
    prints = list(getattr(amt_result, "aggressive_prints", ()) or ())
    if not prints:
        return None

    px = _to_float(getattr(tick, "close", 0.0), default=0.0) or 0.0
    if px <= 0 or buffer <= 0:
        return None

    proximity = px * 0.005
    best = None
    best_size = 0.0

    for item in prints[-10:]:
        side = str(getattr(item, "side", "")).upper()
        ap_price = _to_float(getattr(item, "price", None), default=None)
        if ap_price is None:
            continue
        ap_size = _to_float(getattr(item, "size", None), default=_to_float(getattr(item, "quantity", 0.0), default=0.0))

        if is_buy and side == "SELL" and ap_price < px and abs(ap_price - px) < proximity:
            if best is None or abs(ap_price - px) < abs(best - px) or (
                abs(ap_price - px) == abs(best - px) and ap_size > best_size
            ):
                best = ap_price
                best_size = ap_size

        if (not is_buy) and side == "BUY" and ap_price > px and abs(ap_price - px) < proximity:
            if best is None or abs(ap_price - px) < abs(best - px) or (
                abs(ap_price - px) == abs(best - px) and ap_size > best_size
            ):
                best = ap_price
                best_size = ap_size

    if best is None:
        return None
    if is_buy:
        return (best + buffer) if inside_cluster else (best - buffer)
    return (best - buffer) if inside_cluster else (best + buffer)


def build_entry_signal(
    direction: str,
    tick: "OHLC",
    amt_result: "AMTResult",
    ai_result: dict,
    setup_type: SetupType | None = None,
    data: list["OHLC"] | None = None,
    risk_sl_pct: float | None = None,
    session_context: str = "",
    confidence: str = "Medium",
    session_risk_pct: float | None = None,
    inside_cluster: bool = True,
    inside_extreme: bool = False,
    tick_size: float = 0.05,
) -> Signal:
    """Construct a typed `Signal` from AMT context and confidence context."""
    resolved_setup = setup_type or SetupType.MEAN_REVERSION
    if setup_type is None and isinstance(ai_result, dict):
        raw_setup = str(ai_result.get("setup", "") or "").lower()
        if raw_setup in {"trend", "trend_model", "trend_model_playbook"}:
            resolved_setup = SetupType.TREND_MODEL
        elif raw_setup in {"responsive_fade", "fade", "responsive_fade_playbook"}:
            resolved_setup = SetupType.RESPONSIVE_FADE
        elif raw_setup in {"mean_reversion_playbook", "mean_reversion", "mean_rev"}:
            resolved_setup = SetupType.MEAN_REVERSION

    is_buy = direction == "LONG"
    signal_type = SignalType.BUY if is_buy else SignalType.SELL
    px = _to_float(getattr(tick, "close", 0.0), default=0.0) or 0.0
    buffer = px * 0.001 if not risk_sl_pct else px * float(risk_sl_pct) / 100.0
    vwap = _to_float(getattr(amt_result, "session_vwap", 0), default=0.0) or _to_float(getattr(tick, "vwap", 0), default=0.0) or 0.0

    agg_sl = sl_from_aggressive_print(amt_result, tick, is_buy, buffer, inside_cluster=inside_cluster)
    va_width = abs(_to_float(getattr(amt_result, "value_area_high", 0.0), default=0.0) - _to_float(getattr(amt_result, "value_area_low", 0.0), default=0.0))
    min_reward = px * 0.005

    if resolved_setup == SetupType.RESPONSIVE_FADE:
        tp_price = _to_float(getattr(amt_result, "poc", 0.0), default=0.0)
        fade_target = _to_float(vwap, default=0.0)
        if fade_target and tp_price and abs(px - tp_price) > abs(px - fade_target):
            tp_price = fade_target
        stop = px - max(min_reward * 0.5, px * 0.002) if is_buy else px + max(min_reward * 0.5, px * 0.002)
        allow_trail = True
    elif resolved_setup == SetupType.TREND_MODEL:
        if is_buy:
            if _to_float(getattr(amt_result, "npoc_above", 0.0), default=0.0) > px:
                tp_price = _to_float(getattr(amt_result, "npoc_above", 0.0), default=0.0)
            elif _to_float(getattr(amt_result, "prior_poc", 0.0), default=0.0) > _to_float(getattr(amt_result, "value_area_high", 0.0), default=0.0) and _to_float(getattr(amt_result, "prior_poc", 0.0), default=0.0) > px:
                tp_price = _to_float(getattr(amt_result, "prior_poc", 0.0), default=0.0)
            else:
                tp_price = _to_float(getattr(amt_result, "value_area_high", px), default=px) + max(
                    _to_float(getattr(amt_result, "value_area_high", px), default=px) - _to_float(getattr(amt_result, "poc", px), default=px),
                    0.0,
                )
        else:
            if _to_float(getattr(amt_result, "npoc_below", 0.0), default=0.0) and _to_float(getattr(amt_result, "npoc_below", 0.0), default=0.0) < px:
                tp_price = _to_float(getattr(amt_result, "npoc_below", 0.0), default=px)
            elif _to_float(getattr(amt_result, "prior_poc", 0.0), default=0.0) < _to_float(getattr(amt_result, "value_area_low", 0.0), default=0.0) and _to_float(getattr(amt_result, "prior_poc", 0.0), default=0.0) < px:
                tp_price = _to_float(getattr(amt_result, "prior_poc", 0.0), default=px)
            else:
                tp_price = _to_float(getattr(amt_result, "value_area_low", px), default=px) - max(
                    _to_float(getattr(amt_result, "poc", px), default=px) - _to_float(getattr(amt_result, "value_area_low", px), default=px),
                    0.0,
                )
        extreme_ref = _to_float(getattr(amt_result, "poc", 0.0), default=0.0)
        sl_dir = 1 if (is_buy and not inside_extreme) else -1
        stop = agg_sl if agg_sl is not None else extreme_ref + (sl_dir * buffer)
        allow_trail = True
    else:
        # Default mean-reversion style fallback.
        tp_price = _to_float(getattr(amt_result, "poc", 0.0), default=0.0)
        if _to_float(getattr(amt_result, "prior_poc", 0.0), default=0.0):
            prior_poc = _to_float(getattr(amt_result, "prior_poc", 0.0), default=0.0)
            if is_buy and prior_poc > px:
                tp_price = prior_poc
            if (not is_buy) and prior_poc < px:
                tp_price = prior_poc
        extreme_val = _to_float(getattr(amt_result, "value_area_low", 0.0), default=0.0) if is_buy else _to_float(getattr(amt_result, "value_area_high", 0.0), default=0.0)
        stop = agg_sl if agg_sl is not None else extreme_val + ((1 if is_buy else -1) * buffer if not inside_extreme else (-1 if is_buy else 1) * buffer)
        allow_trail = False

    # Ensure a valid SL/TP and orientation
    if is_buy and stop >= px:
        stop = px - (abs(px * 0.005) if px else 0.5)
    if (not is_buy) and stop <= px:
        stop = px + (abs(px * 0.005) if px else 0.5)

    reward = abs(tp_price - px) if tp_price else 0.0
    risk = abs(px - stop) if stop else 0.0
    if reward < min_reward:
        tp_price = px * (1.02 if is_buy else 0.98)

    # ATR-based clamp when ATR suggests too-tight stop.
    atr = compute_atr(data or [], period=14)
    if atr and risk < (atr * 0.15):
        stop = px - atr * 0.25 if is_buy else px + atr * 0.25

    tick_sz = max(_to_float(tick_size, default=0.05) or 0.05, 0.0001)
    sl_rounded = round_down_to_tick(stop if is_buy else stop, tick_sz) if is_buy else round_up_to_tick(stop if not is_buy else stop, tick_sz)
    tp_rounded = round_up_to_tick(tp_price, tick_sz) if is_buy else round_down_to_tick(tp_price, tick_sz)
    tp_rounded = tp_rounded if tp_rounded > 0 else tp_price
    sl_rounded = sl_rounded if sl_rounded > 0 else stop

    if is_buy and tp_rounded <= sl_rounded:
        tp_rounded = px + max(px * 0.005, abs(px - sl_rounded))
    if not is_buy and tp_rounded >= sl_rounded:
        tp_rounded = px - max(px * 0.005, abs(tp_rounded - px))

    thesis = build_trade_thesis(
        tick=tick,
        amt_result=amt_result,
        setup_type=resolved_setup,
        session_context=session_context or "AMT",
        invalidation_level=float(stop),
    )
    grade = compute_grade_score(
        direction,
        tick,
        amt_result,
        setup_type=resolved_setup,
        session_phase=str(getattr(amt_result, "session_phase", "")),
        favor_strategy=str(getattr(amt_result, "trend", "")),
        profile_shape=str(getattr(amt_result, "profile_shape", "")),
    )

    return Signal.create(
        type=signal_type,
        price=float(px),
        reason=f"setup={resolved_setup.value}|grade={grade}|trail={allow_trail}|confidence={confidence}",
        stop_loss=float(sl_rounded),
        take_profit=float(tp_rounded),
        timestamp=str(getattr(tick, "time", datetime.utcnow().isoformat())),
        setup=resolved_setup,
        source=Source.AMT,
        metadata={
            "setup": resolved_setup.value,
            "direction": direction,
            "grade": grade,
            "allow_trail": allow_trail,
            "thesis": thesis.to_metadata() if thesis else None,
            "confidence": confidence,
            "session_risk_pct": session_risk_pct,
            "poc": getattr(amt_result, "poc", 0.0),
            "poc_vs_price": getattr(amt_result, "poc_vs_price", ""),
            "price_size": {"entry": px, "sl": sl_rounded, "tp": tp_rounded},
        },
    )

