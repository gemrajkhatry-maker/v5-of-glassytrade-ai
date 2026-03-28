"""Pure quant functions for Fabio Playbook entry gates.

All functions are stateless and side-effect-free. They receive data
and return decisions — no threading, no events, no I/O.

Performance optimizations:
- @lru_cache decorators on pure functions for repeated calculations
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from app.domain.trading.models.enums import SignalType, Source, SetupType
from app.domain.trading.models.entities import Signal
from app.domain.fabio_ai.services.trade_thesis import build_trade_thesis

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult, AggressivePrint

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Three-Align Gate
# ------------------------------------------------------------------


def min_candles_gate(data: list, min_candles: int = 6) -> bool:
    """Block entry if insufficient candles have formed since session start.

    Fabio rule: Don't trade first 15-30 minutes.
    Default 6 candles × 5min = 30 minutes.
    Returns True if enough candles exist, False to BLOCK.
    """
    return len(data) >= min_candles


def full_body_close_gate(tick: OHLC, break_level: float, direction: str) -> bool:
    """Fabio rule: Require full body candle close above breakout level.

    Returns True if confirmed, False to BLOCK.
    """
    body = abs(tick.close - tick.open)
    rng = tick.high - tick.low
    body_pct = body / rng if rng > 0 else 0
    if body_pct < 0.5:  # Needs at least 50% body
        return False
    if direction == "LONG" and tick.close > break_level:
        return True
    if direction == "SHORT" and tick.close < break_level:
        return True
    return False


def nearest_round_number(price: float) -> float:
    """Find nearest round number for MCX instruments.

    Uses magnitude-based rounding:
    - Price < 1000: round to 100
    - Price 1000-10000: round to 500
    - Price > 10000: round to 1000
    """
    if price < 1000:
        return round(price / 100) * 100
    elif price < 10000:
        return round(price / 500) * 500
    else:
        return round(price / 1000) * 1000


def cluster_aggressive_prints(
    prints: tuple,
    cluster_pct: float = 0.001,
) -> list[float]:
    """Cluster prints within *cluster_pct* of each other, return VWAP of each cluster.

    Caps at top 5 clusters by total volume.
    """
    if not prints:
        return []

    sorted_prints = sorted(prints, key=lambda p: p.price)
    clusters: list[tuple[float, float]] = []  # (vwap, total_vol)

    current_cluster: list[tuple[float, float]] = [
        (sorted_prints[0].price, sorted_prints[0].volume)
    ]

    for p in sorted_prints[1:]:
        ref_price = current_cluster[0][0]
        if abs(p.price - ref_price) / ref_price <= cluster_pct:
            current_cluster.append((p.price, p.volume))
        else:
            total_vol = sum(v for _, v in current_cluster)
            vwap = sum(pr * v for pr, v in current_cluster) / total_vol
            clusters.append((vwap, total_vol))
            current_cluster = [(p.price, p.volume)]

    # Finalize last cluster
    if current_cluster:
        total_vol = sum(v for _, v in current_cluster)
        vwap = sum(pr * v for pr, v in current_cluster) / total_vol
        clusters.append((vwap, total_vol))

    # Cap at top 5 by volume
    clusters.sort(key=lambda c: c[1], reverse=True)
    return [c[0] for c in clusters[:5]]


# ------------------------------------------------------------------
# BubbleLevel from Footprint (Gap #2)
# ------------------------------------------------------------------


def extract_bubble_levels_from_footprint(
    fp_domain: dict | None,
    min_stacked_count: int = 2,
) -> list[float]:
    """Extract structural levels from stacked imbalances in footprint data.

    These are the highest-conviction signals in institutional trading.
    Stacked imbalances (3+ consecutive 3:1 ratio levels) = strong support/resistance.

    Returns list of price levels where stacked imbalances exist.
    """
    if not fp_domain:
        return []

    bubble_levels: list[float] = []
    try:
        fp_vals = list(fp_domain.values()) if isinstance(fp_domain, dict) else []
        if not fp_vals:
            return []

        # Get recent candles (last 3)
        recent_candles = fp_vals[-3:] if len(fp_vals) >= 3 else fp_vals

        for fp_candle in recent_candles:
            if not hasattr(fp_candle, "levels"):
                continue
            for level in fp_candle.levels:
                # Check if this is a stacked imbalance
                if getattr(level, "stacked", False):
                    price = getattr(level, "price", 0)
                    if price > 0:
                        bubble_levels.append(price)
    except Exception:
        pass

    return bubble_levels


def three_align_check(
    data: list[OHLC],
    amt_result: AMTResult,
    tick: OHLC,
    order_book=None,
    ib_high: float = 0.0,
    ib_low: float = 0.0,
    aggressive_levels: list[float] | None = None,
    footprint_domain: dict | None = None,
    return_is_second_drive: bool = False,
    session_info=None,  # NEW: session context for strategy enforcement
) -> tuple[bool, bool] | tuple[bool, bool, bool]:
    """Three-Align Gate: Market State + Location + Confirmation Bundle.

    FABIO'S RULE: ALL THREE MUST ALIGN.
    1. Market State (BALANCED or IMBALANCED)
    2. Location (price near structural level)
    3. Aggression/Confirmation (volume impulse + delta + spread)

    Additional guards:
    - Second drive enforcement for trend entries (FIX #3)
    - CVD hard block against extreme flow (FIX #5)
    - Session strategy enforcement (FIX #4)

    Returns (gate_passed, confirmation_strong, is_second_drive).
    """
    if (
        amt_result.poc <= 0
        or amt_result.value_area_high <= 0
        or amt_result.value_area_low <= 0
    ):
        return False, False, False

    # Fabio Rule: Don't trade first 15-30 minutes of session
    if not min_candles_gate(data):
        logger.debug("Three-Align: blocked by min_candles_gate (session too young)")
        return False, False, False

    va_range = amt_result.value_area_high - amt_result.value_area_low
    state_ok = (
        amt_result.market_state in ("BALANCED", "IMBALANCED")
        and va_range > amt_result.poc * 0.001
    )
    if not state_ok:
        return False, False, False

    # ── FIX #5 & #8: CVD Hard Gate (adjusted for Indian options) ──
    # Fabio: "If CVD is strongly against you, NO TRADE."
    # FIX #8: Threshold adjusted for options (higher due to gamma/theta effects)
    cvd_slope = getattr(amt_result, "cvd_slope", 0.0)
    cvd_divergence = getattr(amt_result, "cvd_divergence", "")

    # FIX #8: Higher threshold for options (±100 instead of ±50)
    # Options have natural noise from Greeks, need wider threshold
    from app.domain.constants import (
        CVD_SLOPE_EXTREME,
        CVD_SLOPE_HARD_BLOCK,
        CVD_SLOPE_WARNING,
    )

    # Extreme CVD in balance = don't fade (institutional pressure building)
    if cvd_slope < -CVD_SLOPE_EXTREME and amt_result.market_state == "BALANCED":
        logger.info(
            "Three-Align: BLOCKED — CVD extreme selling (%.0f) in balance, do not fade",
            cvd_slope,
        )
        return False, False, False
    if cvd_slope > CVD_SLOPE_EXTREME and amt_result.market_state == "BALANCED":
        logger.info(
            "Three-Align: BLOCKED — CVD extreme buying (+%.0f) in balance, do not fade",
            cvd_slope,
        )
        return False, False, False

    near_level = False
    # Dynamic near-level threshold: 50% of VA width (capped at 3% of price).
    threshold = (
        min(va_range * 0.5, tick.close * 0.03) if va_range > 0 else tick.close * 0.003
    )

    # Collect all structural levels to check against
    levels_to_check: list[float] = [
        amt_result.value_area_high,
        amt_result.value_area_low,
        amt_result.poc,
    ]
    # Developing VA
    if getattr(amt_result, "dev_poc", 0) > 0:
        levels_to_check.extend(
            [amt_result.dev_poc, amt_result.dev_vah, amt_result.dev_val]
        )
    # Displacement leg profile levels
    if getattr(amt_result, "leg_poc", 0) > 0:
        levels_to_check.extend(
            [amt_result.leg_poc, amt_result.leg_vah, amt_result.leg_val]
        )
    # Session VWAP
    if getattr(amt_result, "session_vwap", 0) > 0:
        levels_to_check.append(amt_result.session_vwap)
    # HVNs, LVNs
    levels_to_check.extend((amt_result.hvns or [])[:3])
    levels_to_check.extend(getattr(amt_result, "lvns", []) or [])
    # Leg LVNs (Fabio: LVNs inside impulse leg are reaction zones)
    leg_lvns = getattr(amt_result, "leg_lvns", [])
    if leg_lvns:
        levels_to_check.extend(leg_lvns)
    # IB levels
    for ib_level in [ib_high, ib_low]:
        if ib_level > 0:
            levels_to_check.append(ib_level)
    # Aggressive print cluster levels
    if aggressive_levels:
        levels_to_check.extend(aggressive_levels)
    # Stacked imbalance levels from footprint
    if footprint_domain:
        bubble_levels = extract_bubble_levels_from_footprint(footprint_domain)
        levels_to_check.extend(bubble_levels[:3])
    # Round number awareness (MCX)
    round_lvl = nearest_round_number(tick.close)
    if round_lvl > 0:
        levels_to_check.append(round_lvl)

    active_level = 0.0
    for level in levels_to_check:
        if level > 0 and abs(tick.close - level) < threshold:
            near_level = True
            active_level = level
            break

    # ── Second Drive Detection ──
    is_second_drive = False
    if near_level and data and len(data) > 5:
        history = data[:-1] if data[-1].time == tick.time else data
        recent_touches = 0
        past_touches = 0
        for i, d in enumerate(reversed(history[-30:])):
            dist = min(
                abs(d.high - active_level),
                abs(d.low - active_level),
                abs(d.close - active_level),
            )
            if i < 3:
                if dist < threshold:
                    recent_touches += 1
            else:
                if dist < threshold:
                    past_touches += 1

        if past_touches > 0 and recent_touches == 0:
            is_second_drive = True

    # ── FIX #3: Second Drive Enforcement for Trend Entries ──
    # Fabio: "We wait for the second swing. Don't take the first drive."
    # Only enforce for IMBALANCED (trend) markets.
    # BALANCED (mean reversion) can enter on first drive (fading breakout failure).
    if amt_result.market_state == "IMBALANCED" and near_level and not is_second_drive:
        logger.debug(
            "Three-Align: blocked — first drive only, waiting for re-test (Fabio rule)"
        )
        return False, False, False

    # ── FIX #2: Require Confirmation Bundle ──
    # FABIO RULE: "Direction, Location, AND Aggression — all three."
    # Volume impulse is MANDATORY. Need 2/3 overall.
    agg_ok = check_confirmation_bundle(data, tick, order_book)

    if not agg_ok:
        logger.debug(
            "Three-Align: blocked — confirmation bundle weak (need 2/3: vol/delta/spread)"
        )
        return False, agg_ok, is_second_drive

    # ── All checks passed ──
    gate_passed = state_ok and near_level and agg_ok

    if not return_is_second_drive:
        return gate_passed, agg_ok
    return gate_passed, agg_ok, is_second_drive


# ------------------------------------------------------------------
# Confirmation Bundle
# ------------------------------------------------------------------


def check_confirmation_bundle(data: list[OHLC], tick: OHLC, order_book=None) -> bool:
    """Confirmation Bundle (2/3): Volume Impulse + Delta Pressure + Spread Tightness.

    FABIO RULE: "Aggression is the trigger."
    Volume impulse is MANDATORY — no aggression = no trade.
    Need 2/3 overall, but volume impulse must be present.

    Components:
    1. Volume Impulse: current volume > 1.5x EMA(20) (MANDATORY)
    2. Delta Pressure: |delta| / volume > 0.15 (institutional direction)
    3. Spread Tightness: bid-ask spread <= 5 bps (liquidity)
    """
    if not data or len(data) < 20:
        return False

    alpha = 2.0 / 21  # EMA(20)
    ema_vol = data[-20].volume
    for d in data[-19:]:
        ema_vol = alpha * d.volume + (1.0 - alpha) * ema_vol
    vol_impulse = tick.volume > (ema_vol * 1.5)

    # ── Volume impulse is MANDATORY ──
    # Fabio: "Aggression is the trigger" — without volume impulse,
    # there's no institutional participation.
    if not vol_impulse:
        logger.debug(
            "Confirmation bundle BLOCKED: no volume impulse (vol=%.0f, ema=%.0f)",
            tick.volume,
            ema_vol,
        )
        return False

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
        # In Indian markets, spread data may not be available.
        # Conservative: assume spread is OK if we have volume + delta.
        # This is a pragmatic adaptation for Indian market conditions.
        spread_tight = True

    score = sum([vol_impulse, delta_pressure, spread_tight])
    logger.debug(
        "Confirmation bundle: vol_impulse=%s (vol=%.0f ema=%.0f), delta_pressure=%s (ratio=%.3f), spread_tight=%s -> %d/3",
        vol_impulse,
        tick.volume,
        ema_vol,
        delta_pressure,
        delta_ratio,
        spread_tight,
        score,
    )
    return score >= 2


# ------------------------------------------------------------------
# Momentum Fade Filter (Fabio Rule)
# ------------------------------------------------------------------


def check_momentum_fade(data: list[OHLC], tick: OHLC, direction: str) -> bool:
    """Returns True if entry should be BLOCKED because it fades a freight train.

    Fabio Rule: Do not short a 2.5 sigma bullish impulse on the first touch
    if it has no meaningful rejection wick. (Same for long on bearish impulse).
    """
    if not data or len(data) < 20 or tick.volume <= 0:
        return False

    alpha = 2.0 / 21  # EMA(20)
    ema_vol = data[-20].volume
    for d in data[-19:]:
        ema_vol = alpha * d.volume + (1.0 - alpha) * ema_vol

    # Is it a massive volume spike?
    if tick.volume < (ema_vol * 2.5):
        return False

    body = abs(tick.close - tick.open)
    candle_range = tick.high - tick.low

    # Must be a strong directional candle (body is large part of range)
    if candle_range <= 0 or body < (candle_range * 0.70):
        return False

    upper_wick = tick.high - max(tick.open, tick.close)
    lower_wick = min(tick.open, tick.close) - tick.low

    # Block SHORT entries against strong BULLISH momentum
    if direction == "SHORT" and tick.close > tick.open:
        if upper_wick < (body * 0.3):  # No meaningful rejection wick at the top
            logger.warning(
                "BLOCKED: Attempting to SHORT into 2.5σ bullish momentum without rejection!"
            )
            return True

    # Block LONG entries against strong BEARISH momentum
    if direction == "LONG" and tick.close < tick.open:
        if lower_wick < (body * 0.3):  # No meaningful rejection wick at the bottom
            logger.warning(
                "BLOCKED: Attempting to LONG into 2.5σ bearish momentum without rejection!"
            )
            return True

    return False


# ------------------------------------------------------------------
# Volatility Filter
# ------------------------------------------------------------------


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
    data: list[OHLC] | None = None,
    risk_sl_pct: float | None = None,
    session_context: str = "",
    confidence: str = "Medium",
    session_risk_pct: float | None = None,  # COMPOUNDING: dynamic risk from session
    inside_cluster: bool = True,  # Place SL 1-2 ticks inside aggressive print cluster
    inside_extreme: bool = False,  # Fabio Tip: SL 1-2 ticks INSIDE VAH/VAL/POC
    tick_size: float = 0.05,  # Instrument tick size for SL/TP rounding
) -> Signal:
    """Build Signal from LLM decision using Fabio Playbook SL/TP.

    Mean Reversion: TP at POC, tight SL beyond VA boundary.
    Trend Model:    TP extended beyond VA, wider SL, trailing allowed.
    VWAP used as tighter SL reference when available.

    Position sizing based on confidence:
    - High: 100% base size
    - Medium: 75% base size
    - Low: 50% base size (reduced risk)
    """
    is_buy = direction == "LONG"
    sig_type = SignalType.BUY if is_buy else SignalType.SELL
    buffer = tick.close * 0.001
    vwap = (
        amt_result.session_vwap
        if amt_result.session_vwap > 0
        else (tick.vwap if tick.vwap > 0 else 0)
    )

    agg_sl = sl_from_aggressive_print(
        amt_result,
        tick,
        is_buy,
        buffer,
        inside_cluster=inside_cluster,
    )

    # VA width as proxy for reasonable SL distance
    va_width = abs(amt_result.value_area_high - amt_result.value_area_low)

    # Minimum reward threshold: at least 0.3% of price to avoid dust trades
    min_reward = tick.close * 0.003

    if setup_type == SetupType.MEAN_REVERSION:
        tp_price = amt_result.poc
        if is_buy:
            # Inside Extreme: move SL UP into the safe zone (+buffer)
            # Traditional: move SL DOWN beyond the zone (-buffer)
            extreme_val = amt_result.value_area_low
            sl_dir = 1 if inside_extreme else -1
            stop_price = agg_sl or (extreme_val + (sl_dir * buffer))
            # Cap SL distance: don't risk more than 50% of VA width or 2% of price
            # This cap applies even when aggressive print SL is used
            max_sl_dist = (
                min(va_width * 0.5, tick.close * 0.02)
                if va_width > 0
                else tick.close * 0.005
            )
            if abs(tick.close - stop_price) > max_sl_dist:
                stop_price = tick.close - max_sl_dist
            if not agg_sl and vwap and stop_price < vwap < tick.close:
                stop_price = vwap - buffer
            if (
                tp_price <= tick.close
                or stop_price >= tick.close
                or (tp_price - tick.close) < min_reward
            ):
                tp_price = tick.close * 1.010
                stop_price = tick.close * 0.995
        else:
            # Inside Extreme: move SL DOWN into the safe zone (-buffer)
            # Traditional: move SL UP beyond the zone (+buffer)
            extreme_val = amt_result.value_area_high
            sl_dir = -1 if inside_extreme else 1
            stop_price = agg_sl or (extreme_val + (sl_dir * buffer))
            max_sl_dist = (
                min(va_width * 0.5, tick.close * 0.02)
                if va_width > 0
                else tick.close * 0.005
            )
            if abs(stop_price - tick.close) > max_sl_dist:
                stop_price = tick.close + max_sl_dist
            if not agg_sl and vwap and stop_price > vwap > tick.close:
                stop_price = vwap + buffer
            if (
                tp_price >= tick.close
                or stop_price <= tick.close
                or (tick.close - tp_price) < min_reward
            ):
                tp_price = tick.close * 0.990
                stop_price = tick.close * 1.005
        allow_trail = False
    else:
        if is_buy:
            tp_price = amt_result.value_area_high + (
                amt_result.value_area_high - amt_result.poc
            )
            # Trend SL: move SL INWARD if enabled
            extreme_val = amt_result.poc
            sl_dir = 1 if inside_extreme else -1
            stop_price = agg_sl or (extreme_val + (sl_dir * buffer))
            max_sl_dist = (
                min(va_width * 0.75, tick.close * 0.03)
                if va_width > 0
                else tick.close * 0.01
            )
            if abs(tick.close - stop_price) > max_sl_dist:
                stop_price = tick.close - max_sl_dist
            if not agg_sl and vwap and stop_price < vwap < tick.close:
                stop_price = vwap - buffer
            if tp_price <= tick.close or stop_price >= tick.close:
                tp_price = tick.close * 1.020
                stop_price = tick.close * 0.990
        else:
            tp_price = amt_result.value_area_low - (
                amt_result.poc - amt_result.value_area_low
            )
            # Trend SL: move SL INWARD if enabled
            extreme_val = amt_result.poc
            sl_dir = -1 if inside_extreme else 1
            stop_price = agg_sl or (extreme_val + (sl_dir * buffer))
            max_sl_dist = (
                min(va_width * 0.75, tick.close * 0.03)
                if va_width > 0
                else tick.close * 0.01
            )
            if abs(stop_price - tick.close) > max_sl_dist:
                stop_price = tick.close + max_sl_dist
            if not agg_sl and vwap and stop_price > vwap > tick.close:
                stop_price = vwap + buffer
            if tp_price >= tick.close or stop_price <= tick.close:
                tp_price = tick.close * 0.980
                stop_price = tick.close * 1.010
        allow_trail = True

    # ---- Minimum SL floor ----
    # Options have wider spreads and faster moves than futures.
    # Use ATR-based floor (1x ATR) or 1.5% of price, whichever is larger.
    # This prevents absurdly tight stops that get hit by normal noise.
    atr_val = compute_atr(data, 14) if data and len(data) >= 14 else tick.close * 0.015
    min_sl_dist = max(tick.close * 0.015, atr_val)
    if abs(tick.close - stop_price) < min_sl_dist:
        if is_buy:
            stop_price = tick.close - min_sl_dist
        else:
            stop_price = tick.close + min_sl_dist

    # ---- Cushion SL override ----
    # SessionRiskManager computes dynamic SL% based on session P&L.
    # Apply it if tighter than the current SL (never widen beyond quant SL).
    # IMPORTANT: Never tighten below min_sl_dist — prevents instant stop-outs on MCX options.
    if risk_sl_pct is not None and risk_sl_pct > 0:
        cushion_dist = max(tick.close * risk_sl_pct, min_sl_dist)
        if cushion_dist < abs(tick.close - stop_price):
            if is_buy:
                stop_price = tick.close - cushion_dist
            else:
                stop_price = tick.close + cushion_dist

    setup_label = "MeanRev" if setup_type == SetupType.MEAN_REVERSION else "Trend"
    # ── Round SL/TP to tick_size boundaries (Fabio: clean levels) ──
    from app.domain.services.tick_utils import (
        round_to_tick,
        round_down_to_tick,
        round_up_to_tick,
    )

    if is_buy:
        stop_price = round_down_to_tick(
            float(stop_price), tick_size
        )  # SL below for LONG
        tp_price = round_up_to_tick(float(tp_price), tick_size)  # TP above for LONG
    else:
        stop_price = round_up_to_tick(
            float(stop_price), tick_size
        )  # SL above for SHORT
        tp_price = round_down_to_tick(float(tp_price), tick_size)  # TP below for SHORT

    risk = abs(tick.close - stop_price)
    reward = abs(tp_price - tick.close)
    rr = reward / risk if risk > 0 else 0

    # ── R:R is validated by the gate pipeline; no duplicate check needed here ──
    rr = reward / risk if risk > 0 else 0

    logger.info(
        "build_entry_signal: %s %s entry=%.2f SL=%.2f TP=%.2f risk=%.2f reward=%.2f RR=%.2f "
        "poc=%.2f vah=%.2f val=%.2f vwap=%.2f agg_sl=%s",
        setup_label,
        direction,
        tick.close,
        stop_price,
        tp_price,
        risk,
        reward,
        rr,
        amt_result.poc,
        amt_result.value_area_high,
        amt_result.value_area_low,
        vwap,
        agg_sl,
    )

    thesis = build_trade_thesis(
        tick=tick,
        amt_result=amt_result,
        setup_type=setup_type,
        session_context=session_context,
        invalidation_level=stop_price,
    )

    # Fabio: LVN play increases conviction
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
            # COMPOUNDING: Pass dynamic session risk for position sizing
            "session_risk_pct": session_risk_pct,
        },
    )


def sl_from_aggressive_print(
    amt_result: AMTResult,
    tick: OHLC,
    is_buy: bool,
    buffer: float,
    inside_cluster: bool = False,
) -> float | None:
    """Fabio playbook: SL just beyond the aggressive print cluster + buffer.

    When *inside_cluster* is True (Fabio Gap #13), the buffer direction is
    reversed so the SL sits 1-2 ticks INSIDE the cluster for a tighter stop:
      - LONG:  outside = best - buffer (wider), inside = best + buffer (tighter)
      - SHORT: outside = best + buffer (wider), inside = best - buffer (tighter)
    """
    if not amt_result.aggressive_prints:
        return None
    proximity = tick.close * 0.005
    best = None
    for ap in amt_result.aggressive_prints[-5:]:
        if is_buy and ap.side == "SELL" and ap.price < tick.close:
            if abs(ap.price - tick.close) < proximity:
                if best is None or ap.price > best:
                    best = ap.price
        elif not is_buy and ap.side == "BUY" and ap.price > tick.close:
            if abs(ap.price - tick.close) < proximity:
                if best is None or ap.price < best:
                    best = ap.price
    if best is None:
        return None
    if is_buy:
        return (best + buffer) if inside_cluster else (best - buffer)
    else:
        return (best - buffer) if inside_cluster else (best + buffer)


# ------------------------------------------------------------------
# Option Execution Gates
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# VWAP Bias Check
# ------------------------------------------------------------------


def compute_grade_score(
    direction: str,
    tick: OHLC,
    amt_result: AMTResult,
    setup_type: SetupType,
    session_phase: str = "",
    favor_strategy: str = "",
    profile_shape: str = "",
    footprint_candle=None,
) -> int:
    """Compute A/B/C setup grade score from market confluence."""
    from app.domain.constants import CVD_SLOPE_HARD_BLOCK

    score = 0

    # ── HARD GATE: Extreme CVD Opposition ────────────────────────────
    # Fabio Rule: If CVD is strongly against you, NO TRADE.
    if direction == "LONG" and amt_result.cvd_slope < -CVD_SLOPE_HARD_BLOCK:
        logger.warning(
            f"Grade score killed (CVD Hard Gate): LONG blocked due to extreme bearish CVD ({amt_result.cvd_slope})"
        )
        return -10  # Guaranteed C-grade
    if direction == "SHORT" and amt_result.cvd_slope > CVD_SLOPE_HARD_BLOCK:
        logger.warning(
            f"Grade score killed (CVD Hard Gate): SHORT blocked due to extreme bullish CVD ({amt_result.cvd_slope})"
        )
        return -10  # Guaranteed C-grade

    # CVD confirms direction
    if (direction == "LONG" and amt_result.cvd_slope > 0.3) or (
        direction == "SHORT" and amt_result.cvd_slope < -0.3
    ):
        score += 1
    # No CVD divergence against direction
    if not amt_result.cvd_divergence:
        score += 1
    elif (direction == "LONG" and amt_result.cvd_divergence == "BEARISH_DIV") or (
        direction == "SHORT" and amt_result.cvd_divergence == "BULLISH_DIV"
    ):
        score -= 2

    # Session alignment
    if (
        favor_strategy == "MEAN_REVERSION" and setup_type == SetupType.MEAN_REVERSION
    ) or (
        favor_strategy == "TREND_CONTINUATION" and setup_type == SetupType.TREND_MODEL
    ):
        score += 1

    # Profile shape alignment
    shape_code = profile_shape[0] if profile_shape else ""
    if (shape_code == "b" and direction == "LONG") or (
        shape_code == "P" and direction == "SHORT"
    ):
        score += 1
    elif (shape_code == "b" and direction == "SHORT") or (
        shape_code == "P" and direction == "LONG"
    ):
        score -= 1

    # VWAP bias
    vwap = (
        amt_result.session_vwap
        if amt_result.session_vwap > 0
        else (tick.vwap if tick.vwap > 0 else 0)
    )
    vwap_check = check_vwap_bias(
        direction,
        tick.close,
        vwap,
        getattr(amt_result, "vwap_upper_2", 0),
        getattr(amt_result, "vwap_lower_2", 0),
    )
    if vwap_check.get("overextended"):
        score -= 2
    elif vwap_check.get("warning"):
        score -= 1

    # Stacked imbalance alignment from footprint
    if (
        footprint_candle
        and hasattr(footprint_candle, "levels")
        and footprint_candle.levels
    ):
        stacked = [
            lv for lv in footprint_candle.levels if getattr(lv, "stacked", False)
        ]
        if stacked:
            score += check_imbalance_alignment(direction, stacked)
            # Contested zone (both sides stacked simultaneously) — lowers grade significantly
            has_buy = any(lv.delta > 0 for lv in stacked)
            has_sell = any(lv.delta < 0 for lv in stacked)
            if has_buy and has_sell:
                score -= 3

    # Midday downgrade
    if session_phase == "NSE_MIDDAY":
        score -= 1

    return score


def check_vwap_bias(
    direction: str,
    price: float,
    vwap: float,
    vwap_upper_2: float,
    vwap_lower_2: float,
) -> dict:
    """Check VWAP bias for entry quality.

    Returns {"warning": bool, "overextended": bool}.
    - warning: True if entering against VWAP bias (LONG below VWAP, SHORT above).
    - overextended: True if price is at or beyond the 2-sigma VWAP band.
    """
    if vwap <= 0:
        return {"warning": False, "overextended": False}
    warning = False
    overextended = False
    if direction == "LONG":
        if price < vwap:
            warning = True
        if vwap_upper_2 > 0 and price >= vwap_upper_2:
            overextended = True
    elif direction == "SHORT":
        if price > vwap:
            warning = True
        if vwap_lower_2 > 0 and price <= vwap_lower_2:
            overextended = True
    return {"warning": warning, "overextended": overextended}


def check_imbalance_alignment(direction: str, imbalances: list) -> int:
    """Returns grade_score adjustment based on stacked imbalance alignment.

    +1 if aligned (majority imbalances support direction),
    -2 if opposing (majority imbalances oppose direction),
     0 if empty or evenly mixed.
    """
    if not imbalances:
        return 0
    aligned = sum(
        1
        for im in imbalances
        if (direction == "LONG" and im.direction == "BUY")
        or (direction == "SHORT" and im.direction == "SELL")
    )
    opposing = len(imbalances) - aligned
    if aligned > opposing:
        return 1
    if opposing > aligned:
        return -2
    return 0


# ------------------------------------------------------------------
# Gate Pipeline Integration (Phase 6)
# ------------------------------------------------------------------


def run_gate_pipeline(
    data: list[OHLC],
    amt_result: AMTResult,
    tick: OHLC,
    market_state: str = "BALANCED",
    drive_number: int = 0,
    drive_entry_valid: bool = False,
    aggression_score: float = 0.0,
    is_risk_halted: bool = False,
    halt_reason: str = "",
    tick_age_seconds: float = 1.0,
    symbol: str = "",
    max_distance_to_level_ticks: float = 3.0,
    probing_aggression_threshold: float = 3.0,
    min_aggression_score: float = 2.0,
    max_cushion_ticks: float = 10.0,
    min_rr_ratio: float = 1.5,
    tick_size: float = 0.05,
) -> tuple[bool, str, str]:
    """Run the 12-gate pipeline for additional validation.

    Call this AFTER three_align_check passes. Returns (passed, reason, detail).
    """
    from app.domain.fabio_ai.services.gate_pipeline import GatePipeline, GateContext
    from app.domain.fabio_ai.services.eia_calendar import EIACalendar
    from app.domain.trading.models.enums import MarketState as MS

    # Map string to enum
    state_map = {
        "NO_TRADE": MS.NO_TRADE,
        "BALANCED": MS.BALANCED,
        "BALANCE": MS.BALANCED,
        "IMBALANCED": MS.IMBALANCED,
        "IMBALANCE": MS.IMBALANCED,
        "PROBING": MS.PROBING,
    }
    ms = state_map.get(market_state.upper(), MS.BALANCED)

    # Compute distance to nearest level
    price = float(tick.close)
    levels = [amt_result.value_area_high, amt_result.value_area_low]
    if amt_result.lvns:
        levels.extend(amt_result.lvns)
    nearest = min(levels, key=lambda lv: abs(price - lv)) if levels else 0
    dist_ticks = abs(price - nearest) / tick_size if tick_size > 0 else 999

    # R:R
    risk = (
        abs(price - amt_result.value_area_low)
        if price > amt_result.poc
        else abs(amt_result.value_area_high - price)
    )
    reward = abs(amt_result.poc - price)
    rr = reward / risk if risk > 0 else 0

    # EIA window check (FR-01-07)
    eia_calendar = EIACalendar(suppression_minutes=15)
    eia_suppressed = eia_calendar.is_suppressed(symbol) if symbol else False

    ctx = GateContext(
        symbol=symbol,
        candle_count=len(data),
        tick_age_seconds=tick_age_seconds,
        market_state=ms,
        poc=amt_result.poc,
        vah=amt_result.value_area_high,
        val=amt_result.value_area_low,
        price=price,
        tick_size=tick_size,
        nearest_level=nearest,
        distance_to_level_ticks=dist_ticks,
        drive_number=drive_number,
        drive_entry_valid=drive_entry_valid,
        aggression_score=aggression_score,
        is_risk_halted=is_risk_halted,
        halt_reason=halt_reason,
        eia_window_active=eia_suppressed,
        setup_type=amt_result.setup or "NONE",
        r_r_ratio=rr,
        cushion_ticks=dist_ticks,
        max_distance_to_level_ticks=max_distance_to_level_ticks,
        probing_aggression_threshold=probing_aggression_threshold,
        min_aggression_score=min_aggression_score,
        max_cushion_ticks=max_cushion_ticks,
        min_rr_ratio=min_rr_ratio,
    )

    result = GatePipeline().evaluate(ctx)
    return result.passed, result.reason.value, result.detail


def calculate_position_size(
    equity: float,
    entry_price: float,
    stop_loss: float,
    point_value: float = 10.0,
) -> tuple[int, float, bool]:
    """Calculate position size using PositionSizer (FR-10-01).

    Returns (lots, risk_amount, valid).
    """
    from app.domain.fabio_ai.services.position_sizer import PositionSizer

    ps = PositionSizer.calculate(equity, entry_price, stop_loss, point_value)
    return ps.lots, ps.risk_amount, ps.valid
