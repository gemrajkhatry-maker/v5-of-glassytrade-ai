"""Gate Runner — 5-gate pipeline runner + position sizing wrapper."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_gate_pipeline(
    data,
    amt_result,
    tick,
    market_state: str = "BALANCED",
    drive_number: int = 0,
    drive_entry_valid: bool = False,
    aggression_score: float = 0.0,
    cvd_conflict: bool = False,
    is_risk_halted: bool = False,
    halt_reason: str = "",
    tick_age_seconds: float = 1.1,
    symbol: str = "",
    max_distance_to_level_ticks: float = 3.0,
    probing_aggression_threshold: float = 3.0,
    min_aggression_score: float = 2.0,
    max_cushion_ticks: float = 10.0,
    min_rr_ratio: float = 1.5,
    tick_size: float = 0.05,
    is_extreme_deviation: bool = False,
    pcr: float = 1.0,  # Put-Call Ratio for NSE options bias
    oi_walls: list = None,  # OI walls for NSE protection levels
    favor_strategy: str = "NEUTRAL",  # Session-favored strategy
) -> tuple[bool, str, str, int, int]:
    """Run the 5-gate pipeline for additional validation.

    Call this AFTER three_align_check passes.
    Returns (passed, reason, detail, soft_gates_passed, soft_gates_total).
    """
    from app.domain.fabio_ai.services.gate_pipeline import GatePipeline, GateContext
    from app.domain.fabio_ai.services.eia_calendar import EIACalendar
    from app.domain.trading.models.enums import MarketState as MS

    state_map = {
        "NO_TRADE": MS.BALANCED,  # Map old state to BALANCED
        "BALANCED": MS.BALANCED,
        "BALANCE": MS.BALANCED,
        "IMBALANCED": MS.IMBALANCED,
        "IMBALANCE": MS.IMBALANCED,
        "PROBING": MS.IMBALANCED,  # Map probing to IMBALANCED
    }
    ms = state_map.get(market_state.upper(), MS.BALANCED)

    price = float(tick.close)
    levels = [amt_result.value_area_high, amt_result.value_area_low]
    if amt_result.lvns:
        levels.extend(amt_result.lvns)
    valid_levels = [lv for lv in levels if lv > 0]
    if valid_levels:
        nearest = min(valid_levels, key=lambda lv: abs(price - lv))
        dist_ticks = abs(price - nearest) / tick_size if tick_size > 0 else 999
    else:
        nearest = price
        dist_ticks = 0

    risk = (
        abs(price - amt_result.value_area_low)
        if price > amt_result.poc
        else abs(amt_result.value_area_high - price)
    )
    reward = abs(amt_result.poc - price)
    rr = reward / risk if risk > 0 else 0

    eia_calendar = EIACalendar(suppression_minutes=15)
    eia_suppressed = eia_calendar.is_suppressed(symbol) if symbol else False

    # ── Triple-A / VWAP context ────────────────────────────────────────────
    # Triple-A phase lives on the range-bar state machine, not on AMTResult —
    # leave it unset until that wiring lands.
    triple_a_phase = ""
    vwap_breakout = _detect_vwap_breakout(amt_result, tick, data)
    absorption_side = getattr(amt_result, "absorption_side", "") or ""
    absorption_detected = bool(absorption_side)
    if triple_a_phase:
        logger.debug("gate_runner: triple_a_phase=%s", triple_a_phase)
    if absorption_detected:
        logger.debug(
            "gate_runner: absorption_detected via absorption_side=%s (bar_age unavailable)",
            absorption_side,
        )

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
        cvd_conflict=cvd_conflict,
        is_risk_halted=is_risk_halted,
        halt_reason=halt_reason,
        eia_window_active=eia_suppressed,
        weekly_bias="NEUTRAL",
        weekly_bias_aligned=True,
        is_extreme_deviation=is_extreme_deviation,
        setup_type=amt_result.setup or "NONE",
        r_r_ratio=rr,
        cushion_ticks=dist_ticks,
        max_distance_to_level_ticks=max_distance_to_level_ticks,
        probing_aggression_threshold=probing_aggression_threshold,
        min_aggression_score=min_aggression_score,
        max_cushion_ticks=max_cushion_ticks,
        min_rr_ratio=min_rr_ratio,
        triple_a_phase=triple_a_phase,
        absorption_detected=absorption_detected,
        absorption_bar_age=0,
        vwap_breakout=vwap_breakout,
    )

    result = GatePipeline().evaluate(ctx)
    return (
        result.passed,
        result.reason.value,
        result.detail,
        result.soft_gates_passed,
        result.soft_gates_total,
    )


def _detect_vwap_breakout(amt_result, tick, data) -> str | None:
    """Detect a VWAP-band breakout from AMTResult + current tick volume.

    VWAP std is derived from the committed 1-sigma upper band. Missing data
    (vwap/std/avg volume) degrades to None.
    """
    from app.domain.fabio_ai.services.vwap_breakout import detect_vwap_breakout

    vwap = float(getattr(amt_result, "session_vwap", 0) or 0)
    vwap_upper_1 = float(getattr(amt_result, "vwap_upper_1", 0) or 0)
    std = (vwap_upper_1 - vwap) if (vwap > 0 and vwap_upper_1 > 0) else 0.0
    price = float(getattr(tick, "close", 0) or 0)
    volume = float(getattr(tick, "volume", 0) or 0)
    volumes = [
        float(getattr(d, "volume", 0) or 0)
        for d in (data or [])
        if getattr(d, "volume", 0)
    ]
    avg_volume = sum(volumes) / len(volumes) if volumes else 0.0
    if vwap <= 0 or std <= 0 or price <= 0 or avg_volume <= 0:
        return None
    return detect_vwap_breakout(vwap, std, price, volume, avg_volume)


def calculate_position_size(
    equity: float,
    entry_price: float,
    stop_loss: float,
    point_value: float = 10.0,
    price_velocity: float = 0.0,
    session_realized_pnl: float | None = None,
) -> tuple[int, float, bool]:
    """Calculate position size using PositionSizer.

    Bug #10 fix: Applies velocity-based size scaling after base calculation.
    P1-11 fix: When session_realized_pnl is provided, risk is sized dynamically
    via LossTracker.compute_dynamic_risk (conservative 0.25% after losses);
    otherwise falls back to the fixed RISK_PER_TRADE_PCT.

    Args:
        equity: Account equity.
        entry_price: Entry price.
        stop_loss: Stop loss price.
        point_value: INR value per price point (lot_size × multiplier).
        price_velocity: Price velocity in points/second for size adjustment.
        session_realized_pnl: Optional session realized PnL; when available it
            drives dynamic risk sizing (reduces risk after losses).

    Returns:
        (lots, risk_amount, valid).
    """
    from app.domain.fabio_ai.services.position_sizer import PositionSizer

    if session_realized_pnl is not None:
        from app.domain.fabio_ai.services.loss_tracker import LossTracker

        risk_pct, _risk_mode = LossTracker().compute_dynamic_risk(
            equity, session_realized_pnl
        )
        ps = PositionSizer.calculate(
            equity, entry_price, stop_loss, point_value, risk_pct
        )
    else:
        ps = PositionSizer.calculate(equity, entry_price, stop_loss, point_value)
    if not ps.valid or ps.lots <= 0:
        return ps.lots, ps.risk_amount, ps.valid

    # Apply velocity scaling (Bug #10)
    if price_velocity > 0:
        adjusted_lots, _ = PositionSizer.apply_velocity_scaling(ps.lots, price_velocity)
        if adjusted_lots != ps.lots:
            return adjusted_lots, ps.risk_amount * (adjusted_lots / max(ps.lots, 1)), True

    return ps.lots, ps.risk_amount, ps.valid
