"""Prediction engine service used by AMT strategies."""

from __future__ import annotations

import math

from app.domain.trading.model.enums import Sentiment, TrendDirection
from app.domain.trading.model.value_objects import (
    AIAnalysisResult,
    FactorBreakdown,
    ModelWeights,
    OHLC,
    OrderBook,
)
from dataclasses import dataclass


@dataclass(frozen=True)
class PredictionResult:
    """Prediction payload for downstream callers."""

    predictions: tuple[OHLC, ...] = ()
    analysis: AIAnalysisResult | None = None


def _seeded_random(seed: int) -> float:
    x = math.sin(seed) * 10000
    return x - math.floor(x)


def _calculate_trend(data: list[OHLC], period: int = 50) -> tuple[TrendDirection, float]:
    if len(data) < period:
        return TrendDirection.SIDEWAYS, 0.0

    sample = data[-period:]
    n = len(sample)
    sum_x = 0.0
    sum_y = 0.0
    sum_xy = 0.0
    sum_xx = 0.0
    for i, candle in enumerate(sample):
        close = float(candle.close)
        sum_x += i
        sum_y += close
        sum_xy += i * close
        sum_xx += i * i

    denominator = n * sum_xx - sum_x * sum_x
    if denominator == 0:
        return TrendDirection.SIDEWAYS, 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denominator
    ref = float(sample[0].close)
    rel_slope = slope / ref if ref else 0.0

    if rel_slope > 0.0002:
        return TrendDirection.UP, slope
    if rel_slope < -0.0002:
        return TrendDirection.DOWN, slope
    return TrendDirection.SIDEWAYS, slope


class PredictionEngine:
    """Generate deterministic prediction candles and AI analysis score."""

    def predict(
        self,
        data: list[OHLC],
        weights: ModelWeights,
        count: int = 10,
        order_book: OrderBook | None = None,
    ) -> PredictionResult:
        if len(data) < 50:
            return PredictionResult(
                predictions=(),
                analysis=AIAnalysisResult(
                    sentiment=Sentiment.NEUTRAL.value,
                    confidence=0,
                    long_term_trend=TrendDirection.SIDEWAYS.value,
                    volatility_score=0,
                    quant_score=0,
                    projected_price=0,
                    reasoning=("Insufficient Data",),
                    factor_breakdown=FactorBreakdown(),
                ),
            )

        current_price = float(data[-1].close)
        last_time_ms = 0
        try:
            from datetime import datetime

            last_time_ms = int(datetime.fromisoformat(str(data[-1].time).replace("Z", "+00:00")).timestamp() * 1000)
        except (ValueError, TypeError):
            last_time_ms = len(data) * 300_000

        time_step_ms = 5 * 60 * 1000
        trend_dir, _ = _calculate_trend(data, 50)
        volatility = sum(float(d.high - d.low) for d in data[-10:]) / 10

        mom_period = 14
        mom_data = data[-mom_period:]
        gains = sum(1 for d in mom_data if float(d.close) > float(d.open))
        delta_sum = sum(float(d.delta) for d in mom_data)

        trend_score = 0.0
        if trend_dir == TrendDirection.UP:
            trend_score = 100.0 * float(weights.trend)
        elif trend_dir == TrendDirection.DOWN:
            trend_score = -100.0 * float(weights.trend)

        rsi_proxy = (gains / mom_period) * 100
        momentum_score = (rsi_proxy - 50) * 2 * float(weights.momentum)

        avg_vol = sum(float(d.volume) for d in mom_data) / mom_period if mom_period else 1
        delta_ratio = float(delta_sum) / avg_vol if avg_vol > 0 else 0
        clamped = max(-1.0, min(1.0, delta_ratio))
        delta_score = clamped * 100.0 * float(weights.delta)

        ob_score = 0.0
        if order_book:
            bids = sum(float(b.quantity) for b in order_book.bids)
            asks = sum(float(a.quantity) for a in order_book.asks)
            total = bids + asks
            if total > 0:
                imbalance = (bids - asks) / total
                ob_score = imbalance * 100.0 * float(weights.order_book)

        quant_score = max(-100.0, min(100.0, trend_score + momentum_score + delta_score + ob_score))
        factor_breakdown = FactorBreakdown(
            trend=trend_score,
            momentum=momentum_score,
            delta=delta_score,
            order_book=ob_score,
        )

        if quant_score > 20:
            sentiment = Sentiment.BULLISH
            confidence = abs(quant_score)
        elif quant_score < -20:
            sentiment = Sentiment.BEARISH
            confidence = abs(quant_score)
        else:
            sentiment = Sentiment.NEUTRAL
            confidence = 100 - abs(quant_score)

        projected_price = current_price * (1 + (quant_score / 100.0) * 0.02)

        predictions: list[OHLC] = []
        prev_close = current_price
        base_seed = len(data) * 55
        for i in range(1, count + 1):
            progress = i / count
            factor = 1 - (1 - progress) ** 3
            baseline = current_price + (projected_price - current_price) * factor

            ns = base_seed + i
            noise = (_seeded_random(ns) - 0.5) * volatility * 1.2
            close = baseline + noise
            open_price = prev_close
            body_max = max(open_price, close)
            body_min = min(open_price, close)
            high = max(body_max + _seeded_random(ns + 100) * volatility * 0.5, body_max)
            low = min(body_min - _seeded_random(ns + 200) * volatility * 0.5, body_min)

            vol = 1000.0
            vwap = (high + low + close) / 3.0
            direction = 1.0 if close > open_price else -1.0
            tbv = vol * (0.5 + direction * 0.1)
            delta = (2 * tbv) - vol

            from datetime import datetime, timezone

            ts = datetime.fromtimestamp((last_time_ms + i * time_step_ms) / 1000, tz=timezone.utc).isoformat()
            predictions.append(
                OHLC(
                    time=ts,
                    open=float(open_price),
                    high=float(high),
                    low=float(low),
                    close=float(close),
                    volume=float(vol),
                    vwap=float(vwap),
                    taker_buy_volume=float(tbv),
                    delta=float(delta),
                )
            )
            prev_close = close

        analysis = AIAnalysisResult(
            sentiment=sentiment.value,
            confidence=confidence,
            long_term_trend=trend_dir.value,
            volatility_score=volatility,
            quant_score=quant_score,
            projected_price=projected_price,
            reasoning=(
                f"Quant Score: {quant_score:.0f}",
                f"Trend Weight: {weights.trend * 100:.0f}%",
                f"Order Flow Weight: {weights.delta * 100:.0f}%",
                f"Sentiment: {sentiment.value} ({confidence:.0f}%)",
            ),
            factor_breakdown=factor_breakdown,
        )

        return PredictionResult(predictions=tuple(predictions), analysis=analysis)
