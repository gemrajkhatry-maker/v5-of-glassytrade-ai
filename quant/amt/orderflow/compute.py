"""Order-flow metrics computation — extracted from AMTAnalyzer.

Single responsibility: compute order flow indicators (OBI, OFI, CVD, delta,
absorption, aggression score) from recent data and order book.  No side effects
beyond updating the injected tracker objects.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from quant.contracts.enums import MarketState

if TYPE_CHECKING:
    from quant.contracts.value_objects import OHLC, OrderBook

logger = logging.getLogger(__name__)


def compute_order_flow_metrics(
    recent_data: list,
    order_book: "OrderBook | None",
    current: "OHLC",
    agg_prints: list,
    market_state: MarketState,
    lvns: list,
    vah: float,
    val: float,
    poc: float,
    tick_size: float,
    *,
    cvd_state=None,
    avg_candle_vol: float = 0.0,
    big_trade_detector=None,
    absorption_detector=None,
    ofi_calculator=None,
    bubble_detector=None,
    persistent_agg_scorer=None,
    atr_period: int = 14,
    session_bars: list | None = None,
) -> dict:
    """Compute order flow detectors and RAW aggression components (no direction gating).

    All tracker objects (cvd, big_trade, absorption, ofi, bubble, agg_scorer)
    are injected — this function is a pure mapper, not a god-class method.

    Returns raw component confirmations. Direction-gated aggression scoring is
    delegated to the decision pipeline where the strategy candidate direction
    is resolved (see quant/decision/gates_edge.py).
    """
    result: dict = {}

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

    # FR-06-02: CVD — raw confirmation without direction gating.
    # Direction-gated CVD confirmation is applied in the decision pipeline
    # (gate_triple_a_edge) where the strategy candidate direction is resolved.
    result["cvd_state"] = cvd_state
    result["cvd_confirmed"] = False
    if cvd_state is not None:
        # CVD is confirmed if there's a meaningful slope (non-zero) OR divergence.
        # The direction alignment check happens in the decision pipeline.
        if cvd_state.has_divergence:
            result["cvd_confirmed"] = True
            result["cvd_divergence_type"] = cvd_state.divergence_type
        else:
            result["cvd_confirmed"] = cvd_state.slope != 0
            result["cvd_divergence_type"] = ""

    # FR-06-03: Big trade
    big_trade = big_trade_detector.detect(current, result["avg_candle_vol"]) if big_trade_detector else None
    result["big_trade_confirmed"] = big_trade is not None

    # FR-06-04: Absorption
    atr = _compute_atr(session_bars or recent_data, period=atr_period)
    absorption = absorption_detector.detect(current, atr, result["avg_candle_vol"]) if absorption_detector else None
    result["absorption_detected"] = absorption.detected if absorption else False
    result["absorption_side"] = absorption.side if absorption and absorption.detected else ""
    result["absorption_range_ratio"] = absorption.range_ratio if absorption else 0.0
    result["absorption_vol_ratio"] = absorption.vol_ratio if absorption else 0.0
    result["absorption_active"] = absorption.active if absorption else False
    result["absorption_cluster_high"] = absorption.cluster_high if absorption else 0.0
    result["absorption_cluster_low"] = absorption.cluster_low if absorption else 0.0

    # FR-06-05: OFI
    ofi_result = ofi_calculator.update(current) if ofi_calculator else None
    result["ofi_result"] = ofi_result
    result["ofi_aligned"] = (ofi_result.ofi > 0.10 or ofi_result.ofi < -0.10) if ofi_result else False

    # FR-06-06: Confluence
    result["confluence_bonus"] = False
    for lvn in lvns:
        for level in [vah, val, poc]:
            if level > 0 and abs(lvn - level) < tick_size * 3:
                result["confluence_bonus"] = True
                break

    # FR-06-07: Volume bubble
    bubble = bubble_detector.detect(current) if bubble_detector else None
    result["volume_bubble_near"] = bubble.detected if bubble else False

    # Store raw components for direction-gated re-scoring in decision pipeline.
    # Do NOT compute direction-gated aggression score here.
    result["aggression_components"] = {
        "footprint_confirmed": result["footprint_confirmed"],
        "cvd_confirmed": result["cvd_confirmed"],
        "big_trade_confirmed": result["big_trade_confirmed"],
        "absorption_detected": result["absorption_detected"],
        "ofi_aligned": result["ofi_aligned"],
        "confluence_bonus": result["confluence_bonus"],
        "volume_bubble_near": result["volume_bubble_near"],
    }

    # Call scorer WITHOUT direction (direction gating happens in decision pipeline)
    if persistent_agg_scorer is not None:
        persistent_agg_scorer.set_persistence_for_state(market_state)
        agg_result = persistent_agg_scorer.score(
            footprint_confirmed=result["footprint_confirmed"],
            cvd_confirmed=result["cvd_confirmed"],
            big_trade_confirmed=result["big_trade_confirmed"],
            absorption_detected=result["absorption_detected"],
            ofi_aligned=result["ofi_aligned"],
            confluence_bonus=result["confluence_bonus"],
            volume_bubble_near=result["volume_bubble_near"],
            direction=None,
            cvd_slope=cvd_state.slope if cvd_state is not None else None,
            ofi=ofi_result.ofi if ofi_result else None,
            norm_delta=result["norm_delta"],
            absorption_side=result["absorption_side"],
        )
    else:
        agg_result = None
    result["agg_result"] = agg_result
    result["aggression_score"] = agg_result.score if agg_result else 0.0
    result["has_aggression"] = agg_result.confirmed if agg_result else False

    return result


def _compute_atr(bars: list, period: int = 14) -> float:
    """Average True Range — standalone helper."""
    if len(bars) < 2:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(bars)):
        h = float(bars[i].high)
        l = float(bars[i].low)
        pc = float(bars[i - 1].close)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    window = trs[-period:]
    return sum(window) / max(len(window), 1)


def track_drives(
    live_price: float,
    poc: float,
    lvns: list,
    hvns: list,
    vah: float,
    val: float,
    tick_size: float,
    current: "OHLC",
    drive_tracker=None,
) -> tuple[int, bool]:
    """Classify current price against nearest key level for drive tracking."""
    drive_number: int = 0
    drive_entry_valid: bool = False
    all_levels: list[float] = [poc] + list(lvns) + ([vah, val] if vah > 0 and val > 0 else [])
    if all_levels and live_price > 0:
        nearest = min(all_levels, key=lambda _l: abs(_l - live_price))
        proximity_ticks = abs(live_price - nearest) / max(tick_size, 0.001)
        if proximity_ticks <= 5:
            drive_dir = "LONG" if live_price >= nearest else "SHORT"
            try:
                drive_result = drive_tracker.classify_touch(
                    price=live_price,
                    level=nearest,
                    candle=current,
                    direction=drive_dir,
                    tick_size=tick_size,
                )
                drive_number = drive_result.drive_number
                drive_entry_valid = drive_result.entry_valid
            except Exception:
                logger.debug("Drive detection failed — drive number will be unset", exc_info=True)
    return drive_number, drive_entry_valid
