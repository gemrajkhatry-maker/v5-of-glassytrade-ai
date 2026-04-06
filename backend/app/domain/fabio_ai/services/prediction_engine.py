"""Prediction Engine — AI quant scoring and ghost candle generation.

Pure domain service: calculates a multi-factor quant score using dynamic
weights from the Learning Engine, and generates projected 'ghost' candles.
"""

from __future__ import annotations

import math

from app.domain.trading.models.enums import Sentiment, TrendDirection
from app.domain.trading.models.value_objects import (
    OHLC, OrderBook,
)
from app.domain.fabio_ai.models.predictions import (
    ModelWeights, FactorBreakdown, AIAnalysisResult, PredictionResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seeded_random(seed: int) -> float:
    x = math.sin(seed) * 10000
    return x - math.floor(x)


def _calculate_trend(
    data: list[OHLC], period: int = 50
) -> tuple[TrendDirection, float]:
    if len(data) < period:
        return TrendDirection.SIDEWAYS, 0.0

    sl = data[-period:]
    n = len(sl)
    sum_x = sum_y = sum_xy = sum_xx = 0.0
    for i in range(n):
        sum_x += i
        sum_y += sl[i].close
        sum_xy += i * sl[i].close
        sum_xx += i * i

    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return TrendDirection.SIDEWAYS, 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denom
    rel_slope = slope / sl[0].close if sl[0].close != 0 else 0

    if rel_slope > 0.0002:
        return TrendDirection.UP, slope
    if rel_slope < -0.0002:
        return TrendDirection.DOWN, slope
    return TrendDirection.SIDEWAYS, slope


# ---------------------------------------------------------------------------
# Prediction Engine
# ---------------------------------------------------------------------------

class PredictionEngine:
    """Pure domain service for AI prediction analysis.

    Uses dynamic weights to compute a multi-factor quant score and generates
    projected 'ghost' candles.
    """

    def predict(
        self,
        data: list[OHLC],
        weights: ModelWeights,
        count: int = 10,
        order_book: OrderBook | None = None,
    ) -> PredictionResult:
        if len(data) < 50:
            return PredictionResult(
                analysis=AIAnalysisResult(
                    sentiment=Sentiment.NEUTRAL.value,
                    confidence=0, long_term_trend=TrendDirection.SIDEWAYS.value,
                    volatility_score=0, quant_score=0, projected_price=0,
                    reasoning=("Insufficient Data",),
                    factor_breakdown=FactorBreakdown(),
                ),
            )

        current_price = data[-1].close
        last_time_ms = 0
        try:
            from datetime import datetime
            last_time_ms = int(
                datetime.fromisoformat(data[-1].time.replace("Z", "+00:00")).timestamp() * 1000
            )
        except (ValueError, TypeError):
            last_time_ms = len(data) * 300_000  # fallback

        time_step = 5 * 60 * 1000  # 5 minutes

        # 1. Analysis inputs
        trend_dir, slope = _calculate_trend(data, 50)
        volatility = sum(d.high - d.low for d in data[-10:]) / 10

        mom_period = 14
        mom_data = data[-mom_period:]
        gains = sum(1 for d in mom_data if d.close > d.open)
        delta_sum = sum(d.delta for d in mom_data)

        # 2. Score with dynamic weights
        bd = FactorBreakdown()
        trend_score = 0.0
        if trend_dir == TrendDirection.UP:
            trend_score = 100 * weights.trend
        elif trend_dir == TrendDirection.DOWN:
            trend_score = -100 * weights.trend

        rsi_proxy = (gains / mom_period) * 100
        mom_score = (rsi_proxy - 50) * 2 * weights.momentum

        avg_vol = sum(d.volume for d in mom_data) / mom_period if mom_period else 1
        delta_ratio = delta_sum / avg_vol if avg_vol > 0 else 0
        clamped = max(-1, min(1, delta_ratio))
        delta_score = clamped * 100 * weights.delta

        ob_score = 0.0
        if order_book:
            bids = sum(b.quantity for b in order_book.bids)
            asks = sum(a.quantity for a in order_book.asks)
            total = bids + asks
            if total > 0:
                imbalance = (bids - asks) / total
                ob_score = imbalance * 100 * weights.order_book

        quant_score = max(-100, min(100, trend_score + mom_score + delta_score + ob_score))
        bd = FactorBreakdown(
            trend=trend_score, momentum=mom_score,
            delta=delta_score, order_book=ob_score,
        )

        # 3. Sentiment + Confidence
        if quant_score > 20:
            sentiment = Sentiment.BULLISH
            confidence = abs(quant_score)
        elif quant_score < -20:
            sentiment = Sentiment.BEARISH
            confidence = abs(quant_score)
        else:
            sentiment = Sentiment.NEUTRAL
            confidence = 100 - abs(quant_score)

        # 4. Ghost candles
        percent_move = (quant_score / 100) * 0.02
        projected_price = current_price * (1 + percent_move)

        predictions: list[OHLC] = []
        prev_close = current_price
        base_seed = len(data) * 55

        for i in range(1, count + 1):
            progress = i / count
            factor = 1 - (1 - progress) ** 3
            baseline = current_price + (projected_price - current_price) * factor

            ns = base_seed + i
            noise = (_seeded_random(ns) - 0.5) * volatility * 1.2
            next_close = baseline + noise
            op = prev_close

            body_max = max(op, next_close)
            body_min = min(op, next_close)
            hi = max(body_max + _seeded_random(ns + 100) * volatility * 0.5, body_max)
            lo = min(body_min - _seeded_random(ns + 200) * volatility * 0.5, body_min)

            vol = 1000.0
            vwap = (hi + lo + next_close) / 3
            direction = 1 if next_close > op else -1
            tbv = vol * (0.5 + direction * 0.1)
            dlt = (2 * tbv) - vol

            from datetime import datetime, timezone
            t = datetime.fromtimestamp(
                (last_time_ms + i * time_step) / 1000, tz=timezone.utc
            ).isoformat()

            predictions.append(OHLC(
                time=t, open=op, high=hi, low=lo, close=next_close,
                volume=vol, vwap=vwap, taker_buy_volume=tbv, delta=dlt,
            ))
            prev_close = next_close

        reasoning = (
            f"Quant Score: {quant_score:.0f}",
            f"Trend Weight: {weights.trend * 100:.0f}%",
            f"Order Flow Weight: {weights.delta * 100:.0f}%",
            f"Sentiment: {sentiment.value} ({confidence:.0f}%)",
        )

        return PredictionResult(
            predictions=tuple(predictions),
            analysis=AIAnalysisResult(
                sentiment=sentiment.value,
                confidence=confidence,
                long_term_trend=trend_dir.value,
                volatility_score=volatility,
                quant_score=quant_score,
                projected_price=projected_price,
                reasoning=reasoning,
                factor_breakdown=bd,
            ),
        )
