"""Orderflow pattern detectors (Fabio methodology) — pure functions.

Each detector consumes a recent ``OrderflowCandle`` history (and, for sweep,
an ``OrderbookTracker``) and returns a domain ``Signal`` or ``None``. They are
stateless and deterministic — the ``DeltaEngine`` is rebuilt from the candle
history on each call — so the same tape always yields the same signals
(replay parity is free).
"""

from __future__ import annotations

from tradex_domain.enums import OrderSide
from tradex_domain.strategy import Signal

from tradex_trading.analytics.delta import DeltaEngine
from tradex_trading.analytics.footprint import imbalance_levels
from tradex_trading.analytics.orderbook import OrderbookTracker
from tradex_trading.analytics.orderflow_types import OrderflowCandle


def _feed_delta(candles: list[OrderflowCandle]) -> DeltaEngine:
    eng = DeltaEngine()
    for c in candles:
        eng.compute_from_candle(c)
    return eng


def _signal(
    candle: OrderflowCandle,
    direction: OrderSide,
    strength: float,
    reason: str,
    **metadata: object,
) -> Signal:
    return Signal(
        instrument=candle.instrument,
        direction=direction,
        strength=max(0.0, min(100.0, strength)),
        reason=reason,
        metadata={"pattern": reason, **metadata},
        timestamp=candle.timestamp,
    )


def detect_absorption(
    candles: list[OrderflowCandle],
    *,
    min_aggressive_volume: float = 1000.0,
) -> Signal | None:
    """Delta/price mismatch: buyers absorbing (bearish bar, positive delta) etc."""
    if not candles:
        return None
    candle = candles[-1]
    delta = candle.delta
    if candle.is_bullish and delta <= -min_aggressive_volume:
        return _signal(
            candle, OrderSide.SELL, (abs(delta) / min_aggressive_volume) * 40,
            "absorption", delta=delta, close=float(candle.ohlc.close.value),
        )
    if candle.is_bearish and delta >= min_aggressive_volume:
        return _signal(
            candle, OrderSide.BUY, (abs(delta) / min_aggressive_volume) * 40,
            "absorption", delta=delta, close=float(candle.ohlc.close.value),
        )
    return None


def detect_initiative(
    candles: list[OrderflowCandle],
    *,
    min_delta_threshold: float = 200.0,
    volume_acceleration: float = 1.5,
    min_displacement_ticks: int = 3,
    tick_size: float = 0.05,
    lookback: int = 20,
) -> Signal | None:
    """Aggressive conviction: delta + volume acceleration + body + alignment."""
    if len(candles) < 3:
        return None
    candle = candles[-1]
    delta = candle.delta
    prior = candles[-lookback:-1]
    if not prior:
        return None
    avg_vol = sum(float(c.volume.value) for c in prior) / len(prior)
    body_ticks = candle.body_size / tick_size

    if abs(delta) < min_delta_threshold:
        return None
    if float(candle.volume.value) < volume_acceleration * avg_vol:
        return None
    if body_ticks < min_displacement_ticks:
        return None
    # Delta direction must align with candle direction.
    if delta > 0 and not candle.is_bullish:
        return None
    if delta < 0 and not candle.is_bearish:
        return None

    direction = OrderSide.BUY if delta > 0 else OrderSide.SELL
    side = "buy" if delta > 0 else "sell"
    imbalance_bonus = 1.0 if any(d == side for _, d in imbalance_levels(candle)) else 0.0

    strength = (
        (abs(delta) / min_delta_threshold) * 20
        + (float(candle.volume.value) / max(avg_vol, 1e-9)) * 15
        + min(body_ticks, 10) * 5
        + imbalance_bonus * 10
    )
    return _signal(
        candle, direction, strength, "initiative",
        delta=delta, volume=float(candle.volume.value), avg_volume=avg_vol,
    )


def detect_exhaustion(
    candles: list[OrderflowCandle],
    *,
    lookback: int = 5,
    volume_decline_pct: float = 0.3,
) -> Signal | None:
    """Trend + fading volume/delta: momentum exhaustion → exit warning."""
    if len(candles) < lookback + 1:
        return None
    candle = candles[-1]
    eng = _feed_delta(candles)
    vol_trend = eng.get_volume_trend(lookback)
    delta_roc = eng.get_delta_roc(lookback)
    avg_vol = sum(float(c.volume.value) for c in candles[-lookback:]) / lookback

    # Price trending (recent closes higher) but volume/delta fading.
    recent_closes = [float(c.ohlc.close.value) for c in candles]
    trending_up = recent_closes[-1] > recent_closes[0]
    fading = vol_trend < -volume_decline_pct * max(avg_vol, 1e-9) and delta_roc < 0
    if not fading:
        return None

    direction = OrderSide.SELL if trending_up else OrderSide.BUY
    strength = 40 + abs(vol_trend) / max(avg_vol, 1e-9) * 5 + abs(delta_roc) * 5
    return _signal(
        candle, direction, strength, "exhaustion",
        volume_trend=vol_trend, delta_roc=delta_roc,
    )


def detect_divergence(
    candles: list[OrderflowCandle],
    *,
    lookback: int = 20,
    confirm_ratio: float = 0.8,
) -> Signal | None:
    """Price new extreme but cumulative delta fails to confirm → reversal."""
    if len(candles) < 3:
        return None
    candle = candles[-1]
    window = candles[-lookback:]
    eng = _feed_delta(window)

    closes = [float(c.ohlc.close.value) for c in window]
    cum = [s.cumulative_delta for s in eng.history]
    prior_high = max(closes[:-1])
    prior_low = min(closes[:-1])

    if closes[-1] >= prior_high:
        prior_cum_peak = max(cum[:-1])
        if prior_cum_peak > 0 and cum[-1] < confirm_ratio * prior_cum_peak:
            ratio = cum[-1] / prior_cum_peak
            return _signal(
                candle, OrderSide.SELL, 30 + (1 - ratio) * 40 + 10, "divergence",
                cum_delta=cum[-1], prior_peak=prior_cum_peak,
            )
    if closes[-1] <= prior_low:
        prior_cum_trough = min(cum[:-1])
        if prior_cum_trough < 0 and cum[-1] > confirm_ratio * prior_cum_trough:
            ratio = cum[-1] / prior_cum_trough
            return _signal(
                candle, OrderSide.BUY, 30 + (1 - ratio) * 40 + 10, "divergence",
                cum_delta=cum[-1], prior_trough=prior_cum_trough,
            )
    return None


def detect_sweep(
    tracker: OrderbookTracker,
    candle: OrderflowCandle,
    *,
    min_levels: int = 3,
) -> Signal | None:
    """Thin-book displacement: aggressive order eats ≥N levels → reversal."""
    if tracker.latest_state is None:
        return None
    state = tracker.latest_state
    swept_asks = tracker.count_swept_levels(side="ask")
    swept_bids = tracker.count_swept_levels(side="bid")

    if swept_asks >= min_levels:
        return _signal(
            candle, OrderSide.SELL, 30 + swept_asks * 15 + min(state.ask_depth_5, 100) * 0.2,
            "sweep", swept_levels=swept_asks, side="ask",
        )
    if swept_bids >= min_levels:
        return _signal(
            candle, OrderSide.BUY, 30 + swept_bids * 15 + min(state.bid_depth_5, 100) * 0.2,
            "sweep", swept_levels=swept_bids, side="bid",
        )
    return None


__all__ = [
    "detect_absorption",
    "detect_divergence",
    "detect_exhaustion",
    "detect_initiative",
    "detect_sweep",
]
