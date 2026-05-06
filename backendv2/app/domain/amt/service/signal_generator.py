"""Signal generation — Triple-A signal generation per Fabio spec."""

from __future__ import annotations

import dataclasses

from app.domain.amt.model.amt_models import Absorption, Signal, VolumeProfile

Bar = dict

WAITING = "WAITING"
ABSORBING = "ABSORBING"
ACCUMULATING = "ACCUMULATING"


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bar_close(bar: Bar) -> float:
    return _to_float(bar.get("close", 0.0))


def _safe_delta(bar: Bar) -> float:
    buy = _to_float(bar.get("buyVolume", 0.0))
    sell = _to_float(bar.get("sellVolume", bar.get("volume", 0.0) - buy))
    return buy - sell


def _safe_volume(bar: Bar) -> float:
    return _to_float(bar.get("volume", 0.0))


def _normalise_step(vp: VolumeProfile | None, bars: list[Bar]) -> float:
    if vp is not None and getattr(vp, "step", 0.0):
        return _to_float(vp.step)

    if len(vp.levels) >= 2 if vp is not None else False:
        first = _to_float(vp.levels[0].price)
        second = _to_float(vp.levels[1].price)
        gap = abs(second - first)
        if gap > 0:
            return gap

    if not bars:
        return 1.0
    closes = [_safe_bar_close(bar) for bar in bars if _safe_bar_close(bar) > 0]
    if not closes:
        return 1.0
    min_close = min(closes)
    max_close = max(closes)
    span = max_close - min_close
    if span <= 0:
        return 1.0
    return max(1.0, span / max(10, len(bars)))


def _is_near_level(price: float, level: float, step: float) -> bool:
    tolerance = max(step * 2.5, _to_float(level) * 0.0 + 1.0)
    return abs(price - level) <= tolerance


def _evaluate_rr(entry: float, stop: float, take_profit: float) -> float:
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0
    return abs(take_profit - entry) / risk


def _current_phase(
    bars: list[Bar],
    absorptions: list[Absorption],
    min_accumulation_bars: int,
) -> tuple[str, int, int]:
    """Return (phase, bars_since_absorption, absorption_index)."""
    if not bars:
        return WAITING, 0, -1
    if not absorptions:
        return WAITING, 0, -1

    last_abs = absorptions[-1]
    abs_index = int(_to_float(getattr(last_abs, "bar_index", -1), -1))
    if abs_index < 0 or abs_index >= len(bars):
        return WAITING, 0, -1

    bars_since_abs = max(0, len(bars) - 1 - abs_index)
    if bars_since_abs < min_accumulation_bars:
        return ABSORBING, bars_since_abs, abs_index
    return ACCUMULATING, bars_since_abs, abs_index


def _build_primary_signal(
    *,
    phase: str,
    last_abs: Absorption,
    price: float,
    vwap: float,
    tp_multiplier: float,
    min_rr: float,
    step: float,
    val: float,
    vah: float,
) -> Signal | None:
    if phase != ACCUMULATING:
        return None

    if last_abs.side == "BUY" and price > vwap:
        sl = val - step
        tp = price + (price - sl) * tp_multiplier
        rr = _evaluate_rr(price, sl, tp)
        if rr >= min_rr:
            return Signal(
                type="LONG",
                entry=price,
                sl=sl,
                tp=tp,
                rr=rr,
                confidence=_to_float(getattr(last_abs, "strength", 0.0)),
                reason="Triple-A BUY absorption + R:R >= threshold (primary path)",
            )

    if last_abs.side == "SELL" and price < vwap:
        sl = vah + step
        tp = price - (sl - price) * tp_multiplier
        rr = _evaluate_rr(price, sl, tp)
        if rr >= min_rr:
            return Signal(
                type="SHORT",
                entry=price,
                sl=sl,
                tp=tp,
                rr=rr,
                confidence=_to_float(getattr(last_abs, "strength", 0.0)),
                reason="Triple-A SELL absorption + R:R >= threshold (primary path)",
            )

    return None


def _build_va_fade_signal(
    *,
    phase: str,
    price: float,
    vwap: float,
    step: float,
    tp_multiplier: float,
    min_rr: float,
    val: float,
    vah: float,
    poc: float,
    bar: Bar,
) -> Signal | None:
    if phase != ACCUMULATING:
        return None

    delta = _safe_delta(bar)
    volume = _safe_volume(bar)
    delta_scale = abs(delta) / (volume + 1.0)

    if price <= val + 2 * step and delta > 0 and price <= vwap and _is_near_level(price, val, step):
        sl = val - step
        tp = poc
        rr = _evaluate_rr(price, sl, tp)
        if rr >= min_rr:
            return Signal(
                type="LONG",
                entry=price,
                sl=sl,
                tp=tp,
                rr=rr,
                confidence=min(1.0, delta_scale),
                reason="VA-fade LONG at VAL with delta+VWAP; target POC",
            )

    if price >= vah - 2 * step and delta < 0 and price >= vwap and _is_near_level(price, vah, step):
        sl = vah + step
        tp = poc
        rr = _evaluate_rr(price, sl, tp)
        if rr >= min_rr:
            return Signal(
                type="SHORT",
                entry=price,
                sl=sl,
                tp=tp,
                rr=rr,
                confidence=min(1.0, delta_scale),
                reason="VA-fade SHORT at VAH with delta+VWAP; target POC",
            )

    return None


def generate_signal(
    bars: list[Bar],
    absorptions: list[Absorption],
    vp: VolumeProfile,
    vwap: float,
    tp_multiplier: float = 2.0,
    min_rr: float = 1.5,
) -> dict:
    """
    Generate trading signal dictionary based on Triple-A methodology.
    """
    signal = generate_triple_a_signal(
        bars=bars,
        absorptions=absorptions,
        vp=vp,
        vwap=vwap,
        tp_multiplier=tp_multiplier,
        min_rr=min_rr,
    )
    return {
        "type": signal.type,
        "entry": signal.entry,
        "sl": signal.sl,
        "tp": signal.tp,
        "rr": signal.rr,
        "confidence": signal.confidence,
        "reason": signal.reason,
    }


def generate_triple_a_signal(
    bars: list[Bar],
    absorptions: list[Absorption],
    vp: VolumeProfile | None,
    vwap: float,
    tp_multiplier: float = 2.0,
    min_rr: float = 1.5,
    min_accumulation_bars: int = 2,
) -> Signal:
    """
    Generate Triple-A trading signal.

    This is the main entry point for signal generation that returns
    a Signal value object.
    """
    if not absorptions or not bars:
        return Signal(
            type="NO_TRADE",
            entry=0.0,
            sl=0.0,
            tp=0.0,
            rr=0.0,
            confidence=0.0,
            reason="Triple-A state machine: WAITING (no absorption)",
        )

    last_abs = absorptions[-1]
    phase, bars_since_abs, abs_index = _current_phase(
        bars=bars,
        absorptions=absorptions,
        min_accumulation_bars=min_accumulation_bars,
    )
    if phase != ACCUMULATING:
        bars_needed = max(0, min_accumulation_bars - bars_since_abs)
        reason = (
            f"Triple-A state machine: {phase} "
            f"(need {bars_needed} accumulation bars)"
        )
        return Signal(
            type="NO_TRADE",
            entry=0.0,
            sl=0.0,
            tp=0.0,
            rr=0.0,
            confidence=0.0,
            reason=reason,
        )

    current_bar = bars[-1]
    price = _safe_bar_close(current_bar)

    step = _normalise_step(vp=vp, bars=bars)

    # Default VP values if None
    if vp is None:
        val = 0.0
        vah = 0.0
        poc = 0.0
    else:
        val = _to_float(vp.val)
        vah = _to_float(vp.vah)
        poc = _to_float(vp.poc)

    signal = _build_primary_signal(
        phase=phase,
        last_abs=last_abs,
        price=price,
        vwap=_to_float(vwap),
        tp_multiplier=tp_multiplier,
        min_rr=min_rr,
        step=step,
        val=val,
        vah=vah,
    )
    if signal is not None:
        return dataclasses.replace(
            signal,
            reason=f"{signal.reason}; phase={phase}; bars_since_absorption={bars_since_abs}",
        )

    signal = _build_va_fade_signal(
        phase=phase,
        price=price,
        vwap=_to_float(vwap),
        step=step,
        tp_multiplier=tp_multiplier,
        min_rr=min_rr,
        val=val,
        vah=vah,
        poc=poc,
        bar=current_bar,
    )
    if signal is not None:
        return dataclasses.replace(
            signal,
            reason=f"{signal.reason}; phase={phase}; bars_since_absorption={bars_since_abs}",
        )

    return Signal(
        type="NO_TRADE",
        entry=0.0,
        sl=0.0,
        tp=0.0,
        rr=0.0,
        confidence=0.0,
        reason=f"Triple-A state machine: {phase} (no valid path after conditions)",
    )
