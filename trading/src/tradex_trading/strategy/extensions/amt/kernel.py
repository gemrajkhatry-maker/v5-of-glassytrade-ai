"""Pure closed-candle AMT coordinator."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

from tradex_domain.market import Candle

from tradex_trading.analytics.orderflow_types import OrderflowCandle
from tradex_trading.strategy.extensions.amt.absorption import AbsorptionDetector
from tradex_trading.strategy.extensions.amt.location import location_for, nearest_level
from tradex_trading.strategy.extensions.amt.model import (
    AMTSnapshot,
    AMTStrategyConfig,
    BookSnapshot,
)
from tradex_trading.strategy.extensions.amt.profile import profile
from tradex_trading.strategy.extensions.amt.state_machine import TripleAStateMachine
from tradex_trading.strategy.extensions.amt.vwap import VWAPAccumulator


def _linear_slope(values: Sequence[Decimal]) -> Decimal:
    """Simple linear-regression slope over x = 0..n-1 (archived AMT spec)."""
    n = len(values)
    if n < 2:
        return Decimal("0")
    mean_x = Decimal(n - 1) / Decimal(2)
    mean_y = sum(values, Decimal("0")) / Decimal(n)
    numerator = Decimal("0")
    denominator = Decimal("0")
    for i, y in enumerate(values):
        x = Decimal(i)
        numerator += (x - mean_x) * (y - mean_y)
        denominator += (x - mean_x) ** 2
    return numerator / denominator if denominator else Decimal("0")


def _cvd_divergence(cvd_trend: Decimal, close_trend: Decimal) -> str:
    """Opposite signs of cumulative-delta trend vs close trend -> divergence."""
    if cvd_trend > 0 and close_trend < 0:
        return "BULLISH"
    if cvd_trend < 0 and close_trend > 0:
        return "BEARISH"
    return "NONE"


class AMTKernel:
    """Owns AMT state for one instrument; no bus or execution dependency."""

    def __init__(self, config: AMTStrategyConfig | None = None) -> None:
        self.config = config or AMTStrategyConfig()
        self._candles: list[Candle | OrderflowCandle] = []
        self._vwap = VWAPAccumulator()
        self._machine = TripleAStateMachine(
            self.config.accumulation_bars,
            self.config.max_absorption_age,
        )
        self._absorption = AbsorptionDetector(
            self.config.absorption_volume_multiplier,
            self.config.absorption_range_ratio,
        )
        self._cvd = Decimal("0")
        self._last_delta = Decimal("0")
        self._delta_window: deque[Decimal] = deque(maxlen=self.config.cvd_slope_window)
        self._cvd_window: deque[Decimal] = deque(maxlen=self.config.cvd_slope_window)
        self._close_window: deque[Decimal] = deque(maxlen=self.config.cvd_slope_window)
        self._volume_window: deque[Decimal] = deque(maxlen=20)
        self._last_snapshot: AMTSnapshot | None = None

    def reset(self) -> None:
        self._candles.clear()
        self._vwap = VWAPAccumulator()
        self._machine.reset()
        self._absorption.reset()
        self._cvd = Decimal("0")
        self._last_delta = Decimal("0")
        self._delta_window.clear()
        self._cvd_window.clear()
        self._close_window.clear()
        self._volume_window.clear()
        self._last_snapshot = None

    def update(
        self,
        candle: Candle | OrderflowCandle,
        book: BookSnapshot | None = None,
    ) -> AMTSnapshot:
        if self._candles and candle.timestamp <= self._candles[-1].timestamp:
            raise ValueError("AMT candles must arrive in strictly increasing timestamp order")
        self._candles.append(candle)
        typical = (
            candle.ohlc.high.value
            + candle.ohlc.low.value
            + candle.ohlc.close.value
        ) / Decimal("3")
        self._vwap.update(typical, candle.volume.value)

        flow = candle if isinstance(candle, OrderflowCandle) else None
        delta = (
            Decimal(str(flow.delta))
            if flow is not None
            else self._candle_delta(candle)
        )
        absorption = self._absorption.update(candle)
        prior_volumes = list(self._volume_window)
        avg_volume = (
            sum(prior_volumes, Decimal("0")) / Decimal(len(prior_volumes))
            if prior_volumes
            else Decimal("0")
        )
        aggression_score = (
            candle.volume.value / avg_volume if avg_volume > 0 else Decimal("0")
        )
        self._volume_window.append(candle.volume.value)
        self._last_delta = delta
        self._cvd += delta

        self._delta_window.append(delta)
        self._cvd_window.append(self._cvd)
        self._close_window.append(candle.ohlc.close.value)
        cvd_slope = _linear_slope(self._delta_window)
        cvd_trend = _linear_slope(self._cvd_window)
        close_trend = _linear_slope(self._close_window)

        poc, val, vah, lvn, hvn, shape = profile(self._candles, self.config.value_area_pct)
        ib = self._candles[: self.config.ib_bars]
        ib_high = max((c.ohlc.high.value for c in ib), default=None)
        ib_low = min((c.ohlc.low.value for c in ib), default=None)
        value = self._vwap.value
        std = self._band_width(value)
        location = location_for(candle.ohlc.close.value, val, vah)
        absorption_confirmed = False
        if absorption is not None and book is not None:
            if absorption.side == "BUY" and book.swept_asks > 0:
                absorption_confirmed = True
            elif absorption.side == "SELL" and book.swept_bids > 0:
                absorption_confirmed = True
        snapshot = AMTSnapshot(
            instrument=candle.instrument,
            timestamp=candle.timestamp,
            close=candle.ohlc.close.value,
            poc=poc,
            vah=vah,
            val=val,
            vwap=value,
            upper_1=value + std,
            lower_1=value - std,
            upper_2=value + std * 2,
            lower_2=value - std * 2,
            vwap_std=std,
            delta=delta,
            cvd=self._cvd,
            cvd_slope=cvd_slope,
            cvd_divergence=_cvd_divergence(cvd_trend, close_trend),
            absorption_side=absorption.side if absorption else None,
            absorption_strength=absorption.strength if absorption else Decimal("0"),
            absorption_age=absorption.bar_age if absorption else None,
            ib_high=ib_high,
            ib_low=ib_low,
            ib_complete=len(self._candles) >= self.config.ib_bars,
            location=location,
            nearest_level=nearest_level(candle.ohlc.close.value, poc, val, vah),
            profile_shape=shape,
            lvn_levels=lvn,
            hvn_levels=hvn,
            book_imbalance=book.imbalance_ratio if book else Decimal("0"),
            book_polr=book.path_of_least_resistance if book else "neutral",
            book_swept_bids=book.swept_bids if book else 0,
            book_swept_asks=book.swept_asks if book else 0,
            absorption_confirmed=absorption_confirmed,
            aggression_score=aggression_score,
        )
        result = self._machine.update(snapshot)
        snapshot = replace(snapshot, phase=result.phase, direction=result.direction)
        self._last_snapshot = snapshot
        return snapshot

    def _band_width(self, value: Decimal) -> Decimal:
        """Apply the archived proportional 0.1%-3% VWAP width bounds."""
        return max(
            value * self.config.vwap_min_width_pct,
            min(
                self._vwap.std,
                value * self.config.vwap_max_width_pct,
            ),
        )

    @staticmethod
    def _candle_delta(candle: Candle | OrderflowCandle) -> Decimal:
        if candle.ohlc.close.value > candle.ohlc.open.value:
            return candle.volume.value
        if candle.ohlc.close.value < candle.ohlc.open.value:
            return -candle.volume.value
        return Decimal("0")

    @property
    def snapshot(self) -> AMTSnapshot | None:
        return self._last_snapshot


__all__ = ["AMTKernel"]
