"""Session structure analysis — extracted from AMTAnalyzer.

Single responsibility: classify session structure (day type, market structure,
breaks, NPOC targets, effective market state).  No side effects beyond the
injected classifier's own state.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from quant.contracts.enums import MarketState

if TYPE_CHECKING:
    from quant.contracts.value_objects import OHLC

logger = logging.getLogger(__name__)


def classify_market_structure(
    data: list,
    session_vwap: float,
    market_state: MarketState,
    structure_classifier,
    vwap_history: list,
    poc_history: list,
):
    """Classify market structure and cross-validate against market state."""
    if session_vwap > 0:
        vwap_history.append(session_vwap)
        if len(vwap_history) > 30:
            vwap_history[:] = vwap_history[-30:]
    structure = structure_classifier.classify(data, poc_history, vwap_history)

    # Cross-validation: skip if market_state is BALANCED or IMBALANCED (no PROBING in 2-state model)
    if market_state == MarketState.IMBALANCED and structure.state in ("BALANCE", "CHOP"):
        structure = type(structure)(
            state="TRANSITION",
            confidence_score=max(structure.confidence_score, 60),
            features=structure.features,
        )
    return structure


def detect_breaks(
    recent_data: list,
    vah: float,
    val: float,
    ib_high: float,
    ib_low: float,
    baseline_vol: float,
    live_price: float,
    ib_complete: bool,
    current_break_direction: str,
    *,
    detect_break_fn=None,
    check_ib_break_fn=None,
) -> tuple[dict, str]:
    """Detect initiative/responsive breaks and IB breaks.

    Returns (break_state, new_ib_break_direction).
    """
    from quant.amt.market.break_detector import detect_break, check_ib_break_tick

    break_state = detect_break(recent_data, vah, val, ib_high, ib_low, baseline_vol)
    if break_state is None:
        break_state = {
            "break_direction": "",
            "break_type": "",
            "break_level": 0.0,
            "volume_ratio": 0.0,
        }

    ib_tick_break = check_ib_break_tick(
        live_price=live_price,
        ib_high=ib_high,
        ib_low=ib_low,
        ib_complete=ib_complete,
        current_break_direction=current_break_direction,
    )
    new_ib_break_direction = ""
    if ib_tick_break["break_direction"]:
        new_ib_break_direction = ib_tick_break["break_direction"]
        break_state = {
            "break_direction": ib_tick_break["break_direction"],
            "break_type": ib_tick_break["break_type"],
            "break_level": ib_tick_break["break_level"],
            "volume_ratio": 1.0,
        }
    return break_state, new_ib_break_direction


def compute_noc_targets(
    npoc_tracker,
    underlying: str,
    current: "OHLC",
    tick_size: float,
) -> tuple[float, float]:
    """Check NPOC fills and return nearest targets above/below."""
    npoc_above = 0.0
    npoc_below = 0.0
    if npoc_tracker is not None:
        npoc_tracker.check_and_fill(
            underlying=underlying,
            current_price=float(current.close),
            tick_size=tick_size,
        )
        npoc_result = npoc_tracker.get_active_npocs(
            underlying=underlying,
            current_price=float(current.close),
        )
        if npoc_result.nearest_above:
            npoc_above = npoc_result.nearest_above.price
        if npoc_result.nearest_below:
            npoc_below = npoc_result.nearest_below.price
    return npoc_above, npoc_below


def compute_effective_market_state(
    market_state: MarketState,
    recent_data: list,
    current: "OHLC",
    cvd_source: str = "",
) -> str:
    """Override market state to DEAD when volume is dead."""
    effective: str = market_state.value
    # Option-premium candles are the wrong scale for futures volume EMA — never
    # force DEAD from this gate when AMT is still on option ticks only.
    if cvd_source == "option":
        return effective
    if len(recent_data) >= 20:
        alpha = 2.0 / 21
        ema_vol = float(recent_data[-20].volume)
        for d in recent_data[-19:]:
            ema_vol = alpha * float(d.volume) + (1 - alpha) * ema_vol
        latest_vol = float(recent_data[-1].volume)
        vol_ratio = latest_vol / ema_vol if ema_vol > 0 else 0.0
        if float(current.close) <= 0 or vol_ratio < 0.01:
            effective = MarketState.DEAD.value
    return effective


def compute_per_symbol_delta(option_tick, current_candle: "OHLC | None" = None) -> float:
    """Compute per-symbol normalized delta (-1.0 to +1.0)."""
    if option_tick is not None and getattr(option_tick, "volume", 0) > 0:
        return max(-1.0, min(1.0, float(option_tick.delta) / float(option_tick.volume)))
    if current_candle is not None and getattr(current_candle, "volume", 0) > 0:
        return max(-1.0, min(1.0, float(current_candle.delta) / float(current_candle.volume)))
    return 0.0


def extract_session_open(data: list, current: "OHLC") -> float:
    """Extract session open price from first candle of current date."""
    current_date_prefix = current.time[:10] if len(current.time) >= 10 else ""
    if current_date_prefix:
        for d in data:
            if d.time.startswith(current_date_prefix):
                return d.open
    return data[0].open if data else 0.0


def _compute_developing_va(developing_profile):
    """Compute developing Value Area from incremental profile."""
    dev_poc, dev_vah, dev_val = 0.0, 0.0, 0.0
    if developing_profile is not None:
        dev_profile_data = developing_profile.get_profile()
        if dev_profile_data and len(dev_profile_data) >= 3:
            dev_max_vol = max(p.volume for p in dev_profile_data)
            if dev_max_vol > 0:
                dev_poc_idx = next(
                    i
                    for i, p in enumerate(dev_profile_data)
                    if p.volume == dev_max_vol
                )
                dev_poc = dev_profile_data[dev_poc_idx].price
                dev_total = sum(p.volume for p in dev_profile_data)
                dev_target = dev_total * 0.7
                dev_acc = dev_max_vol
                dev_up, dev_down = dev_poc_idx, dev_poc_idx
                while dev_acc < dev_target:
                    can_up = dev_up + 1 < len(dev_profile_data)
                    can_down = dev_down - 1 >= 0
                    if not can_up and not can_down:
                        break
                    up_vol = dev_profile_data[dev_up + 1].volume if can_up else -1
                    dn_vol = (
                        dev_profile_data[dev_down - 1].volume if can_down else -1
                    )
                    if up_vol >= dn_vol:
                        dev_up += 1
                        dev_acc += dev_profile_data[dev_up].volume
                    else:
                        dev_down -= 1
                        dev_acc += dev_profile_data[dev_down].volume
                dev_step = (
                    (dev_profile_data[1].price - dev_profile_data[0].price)
                    if len(dev_profile_data) > 1
                    else 0
                )
                dev_vah = dev_profile_data[dev_up].price + dev_step / 2
                dev_val = dev_profile_data[dev_down].price - dev_step / 2
    return dev_poc, dev_vah, dev_val
