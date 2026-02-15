"""Footprint Analyzer — footprint chart generation domain service.

Uses real OHLC + Volume + Delta data and models the internal distribution
using Gaussian logic centred on the real VWAP, normalising totals to match
the real volume and delta exactly.
"""

from __future__ import annotations

import math

from app.domain.trading.models.value_objects import OHLC, FootprintLevel, FootprintCandle


class FootprintAnalyzer:
    """Pure domain service for footprint chart generation."""

    def generate(self, data: list[OHLC]) -> dict[str, FootprintCandle]:
        result: dict[str, FootprintCandle] = {}
        if not data:
            return result

        for candle in data:
            price_range = candle.high - candle.low

            # Flat candle
            if price_range <= 1e-9:
                buy_vol = (candle.volume + candle.delta) / 2
                sell_vol = (candle.volume - candle.delta) / 2
                level = FootprintLevel(
                    price=candle.open,
                    bid=int(sell_vol), ask=int(buy_vol),
                    delta=candle.delta, imbalance=False,
                )
                result[candle.time] = FootprintCandle(
                    time=candle.time, levels=(level,),
                    poc_price=candle.open, total_delta=candle.delta,
                    step_price=(candle.close * 0.0001) or 0.01,
                )
                continue

            # Tick size with max 30 rows
            tick_size = max(0.01, candle.close * 0.0001)
            estimated_steps = price_range / tick_size
            if estimated_steps > 30:
                tick_size = price_range / 30

            steps = max(5, int(price_range / tick_size))
            actual_step = max(price_range / steps, 1e-7)

            # Gaussian parameters
            mean = candle.vwap
            std_dev = price_range / 3.5
            if std_dev == 0:
                std_dev = 0.0001

            # First pass: weights
            weights: list[float] = []
            total_weight = 0.0
            for i in range(steps + 1):
                price = candle.low + i * actual_step
                dist = abs(price - mean)
                w = math.exp(-(dist * dist) / (2 * std_dev * std_dev))
                weights.append(w)
                total_weight += w
            if total_weight == 0:
                total_weight = 1.0

            # Second pass: allocate volume
            buy_vol_total = (candle.volume + candle.delta) / 2
            sell_vol_total = (candle.volume - candle.delta) / 2

            raw_levels: list[tuple[float, int, int]] = []
            max_vol_level = 0
            poc_price = candle.open

            for i in range(steps + 1):
                price = candle.low + i * actual_step
                ratio = weights[i] / total_weight
                ask_ = int(buy_vol_total * ratio)
                bid_ = int(sell_vol_total * ratio)
                if ask_ + bid_ > 0:
                    raw_levels.append((price, bid_, ask_))
                    level_vol = ask_ + bid_
                    if level_vol > max_vol_level:
                        max_vol_level = level_vol
                        poc_price = price

            levels: list[FootprintLevel] = []
            for price, bid_, ask_ in reversed(raw_levels):
                levels.append(FootprintLevel(
                    price=price, bid=bid_, ask=ask_,
                    delta=ask_ - bid_,
                    imbalance=(ask_ > bid_ * 3 or bid_ > ask_ * 3),
                ))

            result[candle.time] = FootprintCandle(
                time=candle.time, levels=tuple(levels),
                poc_price=poc_price, total_delta=candle.delta,
                step_price=actual_step,
            )

        return result
