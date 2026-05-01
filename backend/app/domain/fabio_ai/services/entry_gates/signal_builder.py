"""Signal Builder — SL/TP construction from AMT analysis.

Builds Signal objects using Fabio Playbook SL/TP calculation rules:
- Mean Reversion: TP at POC, tight SL beyond VA boundary
- Trend Model: TP extended beyond VA, wider SL, trailing allowed
- VWAP used as tighter SL reference when available
- ATR-based minimum SL floor prevents absurdly tight stops
- Tick-size rounding ensures clean SL/TP levels
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.trading.models.enums import SignalType, Source, SetupType as ST
from app.domain.trading.models.entities import Signal
from app.domain.services.tick_utils import round_down_to_tick, round_up_to_tick
from app.domain.fabio_ai.services.entry_gates.confirmation_bundle import compute_atr
from app.domain.fabio_ai.services.entry_gates.grading import compute_grade_score
from app.domain.fabio_ai.services.trade_thesis import build_trade_thesis

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult

logger = logging.getLogger(__name__)


def sl_from_aggressive_print(
    amt_result: "AMTResult",
    tick: "OHLC",
    is_buy: bool,
    buffer: float,
    inside_cluster: bool = False,
) -> float | None:
    """Fabio playbook: SL just beyond the aggressive print cluster + buffer.

    Fabio's rule: Place stop above the big aggression print, NOT above the high.
    We prefer large prints (size-weighted) as tie-breaker, but proximity is primary.

    When *inside_cluster* is True (Fabio Gap #13), the buffer direction is
    reversed so the SL sits 1-2 ticks INSIDE the cluster for a tighter stop.
    """
    if not amt_result.aggressive_prints:
        return None
    px = float(tick.close)
    proximity = px * 0.005
    best = None
    best_size = 0

    # Prioritize proximity, use size as tie-breaker (Fabio: "big ball" priority)
    for ap in amt_result.aggressive_prints[-10:]:
        if is_buy and ap.side == "SELL" and ap.price < px:
            if abs(ap.price - px) < proximity:
                ap_size = getattr(ap, 'size', 0) or getattr(ap, 'quantity', 0) or 0
                # Prefer larger prints when prices are similar
                if best is None or abs(ap.price - px) < abs(best - px) or \
                   (abs(ap.price - px) == abs(best - px) and ap_size > best_size):
                    best = ap.price
                    best_size = ap_size
        elif not is_buy and ap.side == "BUY" and ap.price > px:
            if abs(ap.price - px) < proximity:
                ap_size = getattr(ap, 'size', 0) or getattr(ap, 'quantity', 0) or 0
                if best is None or abs(ap.price - px) < abs(best - px) or \
                   (abs(ap.price - px) == abs(best - px) and ap_size > best_size):
                    best = ap.price
                    best_size = ap_size

    if best is None:
        return None
    if is_buy:
        return (best + buffer) if inside_cluster else (best - buffer)
    else:
        return (best - buffer) if inside_cluster else (best + buffer)


def build_entry_signal(
    direction: str,
    tick: "OHLC",
    amt_result: "AMTResult",
    ai_result: dict,
    setup_type: "SetupType" = None,
    data: list["OHLC"] | None = None,
    risk_sl_pct: float | None = None,
    session_context: str = "",
    confidence: str = "Medium",
    session_risk_pct: float | None = None,
    inside_cluster: bool = True,
    inside_extreme: bool = False,
    tick_size: float = 0.05,
) -> "Signal":
    """Build Signal from AMT decision using Fabio Playbook SL/TP."""

    if setup_type is None:
        setup_type = ST.MEAN_REVERSION  # default: mean-reversion to POC

    is_buy = direction == "LONG"
    sig_type = SignalType.BUY if is_buy else SignalType.SELL
    px = float(tick.close)
    buffer = px * 0.001
    tp_source = "poc"  # default for MEAN_REVERSION / RESPONSIVE_FADE
    vwap = float(
        amt_result.session_vwap
        if amt_result.session_vwap > 0
        else (tick.vwap if tick.vwap > 0 else 0)
    )
    # Get aggressive print SL (Fabio: stop above big ball)
    agg_sl = sl_from_aggressive_print(amt_result, tick, is_buy, buffer, inside_cluster=inside_cluster)
    va_width = abs(amt_result.value_area_high - amt_result.value_area_low)
    min_reward = px * 0.005

    # Fabio Gap #5: ALWAYS prefer aggressive print SL if available
    # This ensures stop is above institutional aggression, not above arbitrary level

    if setup_type == ST.RESPONSIVE_FADE:
        # FABIO PLAYBOOK: Fade extreme deviation back to Value (POC or VWAP)
        tp_price = amt_result.poc if abs(px - amt_result.poc) > abs(px - vwap) else vwap
        
        # Tight SL just beyond the extreme candle or 1.5σ further
        sl_dist = max(min_reward * 0.5, px * 0.002)
        stop_price = px - sl_dist if is_buy else px + sl_dist
        
        # Ensure we are actually fading (TP must be in opposite direction of deviation)
        if (is_buy and tp_price < px) or (not is_buy and tp_price > px):
            # If TP is wrong way, default to a conservative mean reversion
            tp_price = vwap
            
        allow_trail = True
    elif setup_type == ST.MEAN_REVERSION:
        # Fabio playbook: Mean reversion targets prior POC (previous balance area)
        # When prior POC is available and beyond current price, use it as target
        tp_price = amt_result.poc
        if amt_result.prior_poc > 0:
            # Use prior POC if it's a valid mean reversion target
            # For LONG: prior_poc above current price is good target
            # For SHORT: prior_poc below current price is good target
            if is_buy and amt_result.prior_poc > px:
                tp_price = amt_result.prior_poc
                tp_source = "prior_poc"
            elif not is_buy and amt_result.prior_poc < px:
                tp_price = amt_result.prior_poc
                tp_source = "prior_poc"
        if is_buy:
            extreme_val = amt_result.value_area_low
            sl_dir = 1 if inside_extreme else -1
            stop_price = agg_sl or (extreme_val + (sl_dir * buffer))
            # Fabio: If aggressive print SL exists, use it
            if not agg_sl:
                max_sl_dist = min(va_width * 0.5, px * 0.02) if va_width > 0 else px * 0.005
                if abs(px - stop_price) > max_sl_dist:
                    stop_price = px - max_sl_dist
            if not agg_sl and vwap and stop_price < vwap < px:
                stop_price = vwap - buffer
            if tp_price <= px or stop_price >= px or (tp_price - px) < min_reward:
                tp_price = px * 1.010
                stop_price = px * 0.995
        else:
            extreme_val = amt_result.value_area_high
            sl_dir = -1 if inside_extreme else 1
            stop_price = agg_sl or (extreme_val + (sl_dir * buffer))
            if not agg_sl:
                max_sl_dist = min(va_width * 0.5, px * 0.02) if va_width > 0 else px * 0.005
                if abs(stop_price - px) > max_sl_dist:
                    stop_price = px + max_sl_dist
            if not agg_sl and vwap and stop_price > vwap > px:
                stop_price = vwap + buffer
            if tp_price >= px or stop_price <= px or (px - tp_price) < min_reward:
                tp_price = px * 0.990
                stop_price = px * 1.005
        allow_trail = False
    else:
        # TREND_MODEL — Fabio playbook: target prior balance POC or NPOC.
        # Priority chain: NPOC in direction → prior_poc (if beyond VA) → VA extension (fallback)
        tp_source = "va_extension"  # default fallback

        if is_buy:
            # LONG: prefer npoc_above → prior_poc above VAH → VA extension
            if amt_result.npoc_above > 0 and amt_result.npoc_above > px:
                tp_price = amt_result.npoc_above
                tp_source = "npoc"
            elif amt_result.prior_poc > amt_result.value_area_high and amt_result.prior_poc > px:
                tp_price = amt_result.prior_poc
                tp_source = "prior_poc"
            else:
                tp_price = amt_result.value_area_high + (amt_result.value_area_high - amt_result.poc)

            extreme_val = amt_result.poc
            sl_dir = 1 if inside_extreme else -1
            stop_price = agg_sl or (extreme_val + (sl_dir * buffer))
            # Fabio: If aggressive print SL exists, use it regardless of distance
            if agg_sl:
                pass  # Use aggressive print SL
            else:
                # Only apply max distance if no aggressive print SL
                max_sl_dist = min(va_width * 0.75, px * 0.03) if va_width > 0 else px * 0.01
                if abs(px - stop_price) > max_sl_dist:
                    stop_price = px - max_sl_dist
            if not agg_sl and vwap and stop_price < vwap < px:
                stop_price = vwap - buffer
            if tp_price <= px or stop_price >= px:
                tp_price = px * 1.020
                stop_price = px * 0.990
        else:
            # SHORT: prefer npoc_below → prior_poc below VAL → VA extension
            if amt_result.npoc_below > 0 and amt_result.npoc_below < px:
                tp_price = amt_result.npoc_below
                tp_source = "npoc"
            elif 0 < amt_result.prior_poc < amt_result.value_area_low and amt_result.prior_poc < px:
                tp_price = amt_result.prior_poc
                tp_source = "prior_poc"
            else:
                tp_price = amt_result.value_area_low - (amt_result.poc - amt_result.value_area_low)

            extreme_val = amt_result.poc
            sl_dir = -1 if inside_extreme else 1
            stop_price = agg_sl or (extreme_val + (sl_dir * buffer))
            # Fabio: If aggressive print SL exists, use it regardless of distance
            if agg_sl:
                pass  # Use aggressive print SL
            else:
                max_sl_dist = min(va_width * 0.75, px * 0.03) if va_width > 0 else px * 0.01
                if abs(stop_price - px) > max_sl_dist:
                    stop_price = px + max_sl_dist
            if not agg_sl and vwap and stop_price > vwap > px:
                stop_price = vwap + buffer
            if tp_price >= px or stop_price <= px:
                tp_price = px * 0.980
                stop_price = px * 1.010
        allow_trail = True

    # Minimum SL floor: ATR-based (1x ATR) or 1.5% of price, whichever is larger
    atr_val = compute_atr(data, 14) if data and len(data) >= 14 else px * 0.015
    min_sl_dist = max(px * 0.015, atr_val)
    if abs(px - stop_price) < min_sl_dist:
        stop_price = px - min_sl_dist if is_buy else px + min_sl_dist

    # Cushion SL override (never tighten below min_sl_dist)
    if risk_sl_pct is not None and risk_sl_pct > 0:
        cushion_dist = max(px * risk_sl_pct, min_sl_dist)
        if cushion_dist < abs(px - stop_price):
            stop_price = px - cushion_dist if is_buy else px + cushion_dist

    setup_label = "MeanRev" if setup_type == ST.MEAN_REVERSION else "Trend"
    if setup_label == "Trend" and tp_source != "va_extension":
        setup_label = f"Trend({tp_source})"

    # Compute confluence grade

    grade_score = compute_grade_score(
        direction=direction,
        tick=tick,
        amt_result=amt_result,
        setup_type=setup_type,
        profile_shape=amt_result.profile_shape,
    )

    # Round SL/TP to tick_size boundaries
    if is_buy:
        stop_price = round_down_to_tick(float(stop_price), tick_size)
        tp_price = round_up_to_tick(float(tp_price), tick_size)
    else:
        stop_price = round_up_to_tick(float(stop_price), tick_size)
        tp_price = round_down_to_tick(float(tp_price), tick_size)

    risk = abs(px - stop_price)
    reward = abs(tp_price - px)
    rr = reward / risk if risk > 0 else 0

    logger.info(
        "build_entry_signal: %s %s entry=%.2f SL=%.2f TP=%.2f risk=%.2f reward=%.2f RR=%.2f "
        "poc=%.2f vah=%.2f val=%.2f vwap=%.2f agg_sl=%s",
        setup_label, direction, px, stop_price, tp_price,
        risk, reward, rr,
        amt_result.poc, amt_result.value_area_high, amt_result.value_area_low, vwap, agg_sl,
    )

    thesis = build_trade_thesis(
        tick=tick, amt_result=amt_result, setup_type=setup_type,
        session_context=session_context, invalidation_level=stop_price,
    )
    lvn_multiplier = 1.0
    if amt_result.lvn_play:
        lvn_dir = amt_result.lvn_play.get("direction", "")
        if (is_buy and lvn_dir == "LONG") or (not is_buy and lvn_dir == "SHORT"):
            lvn_multiplier = 1.25
    final_multiplier = (
        1.0 if confidence == "High" else (0.75 if confidence == "Medium" else 0.5)
    ) * lvn_multiplier

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
            "scale_in": True,
            "confidence": confidence,
            "conviction_multiplier": final_multiplier,
            "lvn_play_boost": amt_result.lvn_play is not None,
            "market_state_model": ai_result.get("market_state", "Unknown"),
            "raw_output": ai_result.get("raw_output", "")[:200],
            "trade_thesis": thesis.to_metadata(),
            "session_risk_pct": session_risk_pct,
            "grade_score": grade_score,
            "tp_source": tp_source,
            "entry_lvn": amt_result.lvn_play.get("price", 0.0) if amt_result.lvn_play else 0.0,
        },
    )
