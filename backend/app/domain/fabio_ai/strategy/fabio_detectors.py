"""Fabio Valentini AMT-specific detection utilities.

Extracted from AMTAnalyzer to reduce class size and improve testability.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VAH Probe / IB Test Detection
# ---------------------------------------------------------------------------

def detect_vah_probe(
    live_price: float,
    vah: float,
    ib_high: float,
    vwap_deviation_sigmas: float,
    delta_score: float,
) -> str | None:
    """Detect when price is probing above VAH near IB High — critical AMT state.

    Fabio AMT framework: when price is above VAH and testing IB High,
    this is a pivotal moment that requires special classification.
    """
    if live_price <= vah:
        return None  # Not above VAH

    is_near_ib = ib_high > 0 and abs(live_price - ib_high) / ib_high < 0.01  # Within 1%
    is_extreme = abs(vwap_deviation_sigmas) >= 2.0
    is_delta_flat = abs(delta_score) < 0.1

    if is_near_ib and is_extreme and is_delta_flat:
        return "VAH_PROBE_EXHAUSTION"
    elif is_near_ib and vwap_deviation_sigmas > 0:
        return "VAH_PROBE_TESTING"
    elif live_price > ib_high > 0:
        return "IB_BREAKOUT"

    return None


# ---------------------------------------------------------------------------
# Exhaustion Detection at Extremes
# ---------------------------------------------------------------------------

def check_exhaustion(
    delta_score: float,
    vwap_deviation_sigmas: float,
    aggression: float,
    volume_above_vah_pct: float,
) -> str | None:
    """Detect exhaustion at price extremes.

    Fabio AMT: when price is at extreme but delta is flat,
    the move lacks conviction and may reverse violently.
    """
    warnings: list[str] = []

    # Delta-flat at extreme (the critical signal)
    if abs(delta_score) < 0.1 and abs(vwap_deviation_sigmas) >= 2.0:
        warnings.append("EXHAUSTION: Delta neutral at VWAP extreme — move lacks conviction")

    # Low volume above VAH
    if volume_above_vah_pct < 10.0 and vwap_deviation_sigmas > 1.5:
        warnings.append("THIN_VOLUME: Only {:.1f}% volume above VAH — probe may reverse".format(volume_above_vah_pct))

    # Low aggression at extreme
    if aggression < 1.5 and abs(vwap_deviation_sigmas) >= 2.0:
        warnings.append("LOW_AGGRESSION: Weak participation at price extreme")

    if not warnings:
        return None

    severity = "HIGH" if len(warnings) >= 2 else "MEDIUM"
    return f"[{severity}] " + " | ".join(warnings)


# ---------------------------------------------------------------------------
# Volume Above VAH Computation
# ---------------------------------------------------------------------------

def compute_volume_above_vah(profile: list, vah: float) -> float:
    """Compute percentage of volume above VAH."""
    if not profile or vah <= 0:
        return 0.0

    total_vol = sum(level.volume for level in profile)
    if total_vol <= 0:
        return 0.0

    vol_above = sum(level.volume for level in profile if level.price > vah)
    return (vol_above / total_vol) * 100


# ---------------------------------------------------------------------------
# Developing VA Computation
# ---------------------------------------------------------------------------

def compute_developing_va(developing_profile) -> tuple[float, float, float]:
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


# ---------------------------------------------------------------------------
# Session Helpers
# ---------------------------------------------------------------------------

def extract_session_open(data, current) -> float:
    """Extract session open price from first candle of current date."""
    current_date_prefix = current.time[:10] if len(current.time) >= 10 else ""
    if current_date_prefix:
        for d in data:
            if d.time.startswith(current_date_prefix):
                return d.open
    return data[0].open if data else 0.0


def classify_day_type(data, ib_complete, ib_high, ib_low) -> str:
    """Classify day type: NORMAL, NEUTRAL, TREND, NORMAL_VARIATION."""
    if not ib_complete or ib_high <= 0 or ib_low <= 0:
        return "UNKNOWN"
    session_high = max(d.high for d in data)
    session_low = min(d.low for d in data)
    ib_range = ib_high - ib_low
    if ib_range <= 0:
        return "UNKNOWN"
    dist_above = max(0.0, session_high - ib_high)
    dist_below = max(0.0, ib_low - session_low)
    if dist_above == 0 and dist_below == 0:
        return "NORMAL"
    elif dist_above > 0 and dist_below > 0:
        return "NEUTRAL"
    elif dist_above > ib_range or dist_below > ib_range:
        return "TREND"
    return "NORMAL_VARIATION"


# ---------------------------------------------------------------------------
# Effective Market State
# ---------------------------------------------------------------------------

def compute_effective_market_state(
    market_state,
    recent_data,
    current,
    cvd_source: str = "",
) -> str:
    """Override market state to DEAD when volume is dead."""
    _effective_market_state: str = market_state.value
    # Option-premium candles are the wrong scale for futures volume EMA — never
    # force DEAD from this gate when AMT is still on option ticks only.
    if cvd_source == "option":
        return _effective_market_state
    if len(recent_data) >= 20:
        _alpha = 2.0 / 21
        _ema_vol = float(recent_data[-20].volume)
        for _d in recent_data[-19:]:
            _ema_vol = _alpha * float(_d.volume) + (1 - _alpha) * _ema_vol
        _latest_vol = float(recent_data[-1].volume)
        _vol_ratio = _latest_vol / _ema_vol if _ema_vol > 0 else 0.0
        if float(current.close) <= 0 or _vol_ratio < 0.01:
            _effective_market_state = "DEAD"
    return _effective_market_state


# ---------------------------------------------------------------------------
# Per-Symbol Delta
# ---------------------------------------------------------------------------

def compute_per_symbol_delta(option_tick) -> float:
    """Compute per-symbol delta from option tick (not underlying)."""
    if option_tick is not None and option_tick.volume > 0:
        return float(option_tick.delta) / float(option_tick.volume)
    return 0.0


# ---------------------------------------------------------------------------
# NPOC Targets
# ---------------------------------------------------------------------------

def compute_noc_targets(npoc_tracker, underlying, current, tick_size) -> tuple[float, float]:
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


# ---------------------------------------------------------------------------
# Tick Size Computation
# ---------------------------------------------------------------------------

def compute_tick_size(recent_data, default: float = 0.05) -> float:
    """Compute tick size from recent price data."""
    prices = sorted(set(float(d.close) for d in recent_data[-50:]))
    return min(
        (
            prices[i + 1] - prices[i]
            for i in range(len(prices) - 1)
            if prices[i + 1] > prices[i]
        ),
        default=default,
    )


# ---------------------------------------------------------------------------
# Value Area Computation
# ---------------------------------------------------------------------------

def compute_value_area(
    profile: list,
    poc_index: int,
    value_area_pct: float = 0.7,
) -> tuple[float, float, int, int]:
    """Compute Value Area using CME two-row pairs method.
    
    Returns (vah, val, up_idx, down_idx).
    """
    from app.domain.constants import VALUE_AREA_PCT
    
    total_volume = sum(p.volume for p in profile)
    target_volume = total_volume * (value_area_pct or VALUE_AREA_PCT)
    current_volume = max(p.volume for p in profile)
    up_idx, down_idx = poc_index, poc_index

    while current_volume < target_volume:
        up_pair = 0.0
        up_count = 0
        for k in range(1, 3):
            if up_idx + k < len(profile):
                up_pair += profile[up_idx + k].volume
                up_count += 1
        down_pair = 0.0
        down_count = 0
        for k in range(1, 3):
            if down_idx - k >= 0:
                down_pair += profile[down_idx - k].volume
                down_count += 1

        can_go_up = up_count > 0
        can_go_down = down_count > 0

        if not can_go_up and not can_go_down:
            break

        if can_go_up and (not can_go_down or up_pair >= down_pair):
            for k in range(1, up_count + 1):
                if up_idx + k < len(profile):
                    up_idx += 1
                    current_volume += profile[up_idx].volume
        elif can_go_down:
            for k in range(1, down_count + 1):
                if down_idx - k >= 0:
                    down_idx -= 1
                    current_volume += profile[down_idx].volume

    return up_idx, down_idx


# ---------------------------------------------------------------------------
# Order Flow Metrics
# ---------------------------------------------------------------------------

def compute_order_flow_metrics(
    recent_data: list,
    order_book,
    current,
    agg_prints: list,
    market_state,
    lvns: list,
    vah: float,
    val: float,
    poc: float,
    tick_size: float,
    big_trade_detector,
    absorption_detector,
    bubble_detector,
    ofi_calculator,
    persistent_agg_scorer,
    cvd_tracker,
) -> dict:
    """Compute order flow detectors and aggression score."""
    from app.domain.trading.models.enums import MarketState
    
    result = {}

    # Average volume
    result["avg_candle_vol"] = (
        sum(float(d.volume) for d in recent_data) / len(recent_data)
        if recent_data
        else 0.0
    )

    # OBI from order book
    result["obi"] = 0.0
    result["toxicity"] = 0.0
    if order_book:
        bids_q = sum(b.quantity for b in order_book.bids)
        asks_q = sum(a.quantity for a in order_book.asks)
        total = bids_q + asks_q
        if total > 0:
            result["obi"] = (bids_q - asks_q) / total
        if len(order_book.bids) >= 3 and len(order_book.asks) >= 3:
            top_bids_q = sum(b.quantity for b in order_book.bids[:3])
            top_asks_q = sum(a.quantity for a in order_book.asks[:3])
            top_total = top_bids_q + top_asks_q
            if top_total > 0:
                top_obi = (top_bids_q - top_asks_q) / top_total
                if abs(top_obi) > 0.7:
                    result["toxicity"] = top_obi

    result["norm_delta"] = (
        current.delta / current.volume if current.volume > 0 else 0
    )

    # FR-06-01: Footprint imbalance
    has_agg_prints = len(agg_prints) >= 2
    has_strong_delta = abs(result["norm_delta"]) > 0.30
    result["footprint_confirmed"] = has_agg_prints and has_strong_delta

    # FR-06-02: CVD
    cvd_state = cvd_tracker.state()
    result["cvd_state"] = cvd_state
    result["cvd_confirmed"] = False
    if market_state == MarketState.IMBALANCED and cvd_state.slope > 0:
        result["cvd_confirmed"] = True
    elif market_state == MarketState.IMBALANCED and cvd_state.slope < 0:
        result["cvd_confirmed"] = True
    elif cvd_state.has_divergence:
        result["cvd_confirmed"] = True

    # FR-06-03: Big trade
    big_trade = big_trade_detector.detect(current, result["avg_candle_vol"])
    result["big_trade_confirmed"] = big_trade is not None

    # FR-06-04: Absorption
    atr = (
        max(d.high for d in recent_data[-14:])
        - min(d.low for d in recent_data[-14:])
    ) / max(len(recent_data[-14:]), 1)
    absorption = absorption_detector.detect(current, atr, result["avg_candle_vol"])
    result["absorption_detected"] = absorption.detected
    result["absorption_side"] = absorption.side if absorption.detected else ""
    result["absorption_range_ratio"] = absorption.range_ratio
    result["absorption_vol_ratio"] = absorption.vol_ratio

    # FR-06-05: OFI
    ofi_result = ofi_calculator.update(current)
    result["ofi_result"] = ofi_result
    result["ofi_aligned"] = (ofi_result.ofi > 0.10) or (ofi_result.ofi < -0.10)

    # FR-06-06: Confluence
    result["confluence_bonus"] = False
    for lvn in lvns:
        for level in [vah, val, poc]:
            if level > 0 and abs(lvn - level) < tick_size * 3:
                result["confluence_bonus"] = True
                break

    # FR-06-07: Volume bubble
    bubble = bubble_detector.detect(current)
    result["volume_bubble_near"] = bubble.detected

    # Aggression scorer
    persistent_agg_scorer.set_persistence_for_state(market_state)
    agg_result = persistent_agg_scorer.score(
        footprint_confirmed=result["footprint_confirmed"],
        cvd_confirmed=result["cvd_confirmed"],
        big_trade_confirmed=result["big_trade_confirmed"],
        absorption_detected=result["absorption_detected"],
        ofi_aligned=result["ofi_aligned"],
        confluence_bonus=result["confluence_bonus"],
        volume_bubble_near=result["volume_bubble_near"],
    )
    result["agg_result"] = agg_result
    result["aggression_score"] = agg_result.score
    result["has_aggression"] = agg_result.confirmed

    return result


# ---------------------------------------------------------------------------
# Market Structure Classification
# ---------------------------------------------------------------------------

def classify_market_structure(
    data: list,
    session_vwap: float,
    market_state,
    structure_classifier,
    poc_tracker_internal,
    vwap_history: list,
) -> "MarketStructureResult":
    """Classify market structure and cross-validate against market state.
    
    Note: vwap_history is mutated in place. Caller must handle lazy init of classifier.
    """
    from app.domain.trading.models.enums import MarketState as MS
    
    if session_vwap > 0:
        vwap_history.append(session_vwap)
        if len(vwap_history) > 30:
            vwap_history[:] = vwap_history[-30:]
    
    structure = structure_classifier.classify(
        data,
        poc_tracker_internal._poc_history if hasattr(poc_tracker_internal, '_poc_history') else [],
        vwap_history,
    )

    # Cross-validation: PROBING is incompatible with BALANCE or CHOP
    if market_state == MS.PROBING and structure.state in ("BALANCE", "CHOP"):
        structure = type(structure)(
            state="TRANSITION",
            confidence_score=max(structure.confidence_score, 60),
            features=structure.features,
        )
    return structure


# ---------------------------------------------------------------------------
# Drive Tracking
# ---------------------------------------------------------------------------

def track_drives(
    live_price: float,
    poc: float,
    lvns: list,
    hvns: list,
    vah: float,
    val: float,
    tick_size: float,
    current,
    drive_tracker,
) -> tuple[int, bool]:
    """Classify current price against nearest key level for drive tracking.
    
    Returns (drive_number, drive_entry_valid).
    """
    import logging
    logger = logging.getLogger(__name__)
    
    _drive_number: int = 0
    _drive_entry_valid: bool = False
    _all_levels: list[float] = [poc] + list(lvns) + ([vah, val] if vah > 0 and val > 0 else [])
    if _all_levels and live_price > 0:
        _nearest = min(_all_levels, key=lambda _l: abs(_l - live_price))
        _proximity_ticks = abs(live_price - _nearest) / max(tick_size, 0.001)
        if _proximity_ticks <= 5:
            _drive_dir = "LONG" if live_price >= _nearest else "SHORT"
            try:
                _drive_result = drive_tracker.classify_touch(
                    price=live_price,
                    level=_nearest,
                    candle=current,
                    direction=_drive_dir,
                    tick_size=tick_size,
                )
                _drive_number = _drive_result.drive_number
                _drive_entry_valid = _drive_result.entry_valid
            except Exception:
                logger.debug("Drive detection failed — drive number will be unset", exc_info=True)
    return _drive_number, _drive_entry_valid


# ---------------------------------------------------------------------------
# Baseline Volume & VWAP Bands
# ---------------------------------------------------------------------------

def compute_session_baseline_vol(
    prior_session_avg_volume: float,
    recent_data: list,
) -> float:
    """Compute baseline volume for acceptance/rejection.
    
    Uses prior session average when available, falls back to rolling average.
    """
    if prior_session_avg_volume > 0:
        return prior_session_avg_volume
    return (
        sum(d.volume for d in recent_data[-20:]) / min(20, len(recent_data))
        if recent_data
        else 0.0
    )


def compute_vwap_bands(
    session_vwap: float,
    current,
    vwap_cum_vol: float,
    vwap_price_deviations: list,
    logger=None,
) -> tuple[float, float, float, float, float, float | None]:
    """Compute VWAP standard deviation bands (±1σ, ±2σ).
    
    Returns (vwap_upper_1, vwap_lower_1, vwap_upper_2, vwap_lower_2, vwap_std, vwap_deviation_sigmas).
    """
    import math
    
    vwap_std = 0.0
    if vwap_cum_vol > 0 and len(vwap_price_deviations) > 1:
        mean_deviation = sum(vwap_price_deviations) / len(vwap_price_deviations)
        variance = sum((d - mean_deviation) ** 2 for d in vwap_price_deviations) / len(vwap_price_deviations)
        vwap_std = math.sqrt(max(0.0, variance))

        MIN_VWAP_STD = 1.0
        if vwap_std < MIN_VWAP_STD:
            vwap_std = MIN_VWAP_STD
        
        MAX_VWAP_STD = session_vwap * 0.10
        if vwap_std > MAX_VWAP_STD:
            if logger:
                logger.warning(
                    "VWAP std clamped from %.2f to %.2f (max 10%% of VWAP=%.2f)",
                    vwap_std, MAX_VWAP_STD, session_vwap
                )
            vwap_std = MAX_VWAP_STD

    vwap_upper_1 = session_vwap + vwap_std
    vwap_lower_1 = session_vwap - vwap_std
    vwap_upper_2 = session_vwap + 2 * vwap_std
    vwap_lower_2 = session_vwap - 2 * vwap_std

    live_price = float(current.close)
    vwap_deviation_sigmas: float | None = (
        (live_price - session_vwap) / vwap_std if vwap_std > 0 else None
    )
    
    if vwap_deviation_sigmas is not None and abs(vwap_deviation_sigmas) > 4.0:
        if logger:
            logger.warning(
                "VWAP deviation clamped: %.2fσ → ±4.0σ (vwap=%.2f, live=%.2f, std=%.2f)",
                vwap_deviation_sigmas, session_vwap, live_price, vwap_std
            )
        vwap_deviation_sigmas = 4.0 if vwap_deviation_sigmas > 0 else -4.0
    elif vwap_deviation_sigmas is not None and abs(vwap_deviation_sigmas) > 10:
        if logger:
            logger.warning(
                "VWAP deviation extreme: %.2fσ — possible data source mismatch "
                "(vwap=%.2f, live=%.2f, std=%.2f)",
                vwap_deviation_sigmas, session_vwap, live_price, vwap_std
            )
    return vwap_upper_1, vwap_lower_1, vwap_upper_2, vwap_lower_2, vwap_std, vwap_deviation_sigmas

# ---------------------------------------------------------------------------
# Value Area Bounds Computation
# ---------------------------------------------------------------------------

def compute_value_area_bounds(
    profile: list,
    poc_index: int,
    vwap_ref: float,
) -> tuple[float, float, float, float, float]:
    """Compute POC, VAH, VAL from volume profile using CME two-row pairs method.
    
    Returns (poc, vah, val, step, half_step).
    """
    from app.domain.constants import VALUE_AREA_PCT
    
    poc = profile[poc_index].price
    
    total_volume = sum(p.volume for p in profile)
    target_volume = total_volume * VALUE_AREA_PCT
    current_volume = max(p.volume for p in profile)
    up_idx, down_idx = poc_index, poc_index

    while current_volume < target_volume:
        up_pair = 0.0
        up_count = 0
        for k in range(1, 3):
            if up_idx + k < len(profile):
                up_pair += profile[up_idx + k].volume
                up_count += 1
        down_pair = 0.0
        down_count = 0
        for k in range(1, 3):
            if down_idx - k >= 0:
                down_pair += profile[down_idx - k].volume
                down_count += 1

        can_go_up = up_count > 0
        can_go_down = down_count > 0

        if not can_go_up and not can_go_down:
            break

        if can_go_up and (not can_go_down or up_pair >= down_pair):
            for k in range(1, up_count + 1):
                if up_idx + k < len(profile):
                    up_idx += 1
                    current_volume += profile[up_idx].volume
        elif can_go_down:
            for k in range(1, down_count + 1):
                if down_idx - k >= 0:
                    down_idx -= 1
                    current_volume += profile[down_idx].volume

    step = profile[1].price - profile[0].price if len(profile) > 1 else 0
    half_step = step / 2
    vah = profile[up_idx].price + half_step
    val = profile[down_idx].price - half_step
    
    return poc, vah, val, step, half_step
