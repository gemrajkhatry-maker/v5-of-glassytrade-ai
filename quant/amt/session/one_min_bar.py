"""1-Min Bar Engine — 60-second bar aggregation for scalping.

Runs alongside the 5-min structural pipeline. Provides:
  - 1-min volume profile (rolling 30-min window)
  - 1-min CVD (slope over 10 bars)
  - 1-min aggression score
  - 1-min bar close trigger for MTF signal merger
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from quant.contracts.value_objects import OHLC
from quant.contracts.timezones import IST

logger = logging.getLogger(__name__)




@dataclass(frozen=True)
class OneMinBarState:
    """Immutable 1-min bar state snapshot."""

    close: float
    volume: float
    cvd_slope: float
    aggression: float
    bar_time: str
    is_new_bar: bool


class OneMinBarEngine:
    """60-second bar aggregator for scalping MTF analysis.

    Produces 1-min bars from tick data, maintains CVD slope,
    and provides aggression scoring.
    """

    def __init__(self, cvd_window: int = 10) -> None:
        self._cvd_window = cvd_window
        self._bar_states: dict[str, dict] = {}
        self._cvd_bars: dict[str, list[float]] = {}  # rolling CVD per bar

    def _get_bar_state(self, symbol: str) -> dict:
        if symbol not in self._bar_states:
            self._bar_states[symbol] = {
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "close": 0.0,
                "volume": 0.0,
                "buy_vol": 0.0,
                "sell_vol": 0.0,
                "delta": 0.0,
                "bar_time": "",
                "started": False,
            }
            self._cvd_bars[symbol] = []
        return self._bar_states[symbol]

    def update(
        self,
        symbol: str,
        price: float,
        volume: float,
        delta: float,
        timestamp: str,
    ) -> OneMinBarState:
        """Process a tick. Returns current 1-min bar state."""
        bs = self._get_bar_state(symbol)

        # Determine bar minute
        try:
            dt = datetime.fromisoformat(timestamp)
            bar_minute = dt.replace(second=0, microsecond=0)
            bar_time = bar_minute.isoformat()
        except (ValueError, TypeError):
            bar_time = timestamp

        is_new_bar = bar_time != bs["bar_time"]

        if is_new_bar and bs["started"]:
            # Finalize previous bar
            bar_cvd = bs["delta"]
            cvd_list = self._cvd_bars[symbol]
            cvd_list.append(bar_cvd)
            if len(cvd_list) > self._cvd_window:
                cvd_list.pop(0)

            # Start new bar
            bs["open"] = price
            bs["high"] = price
            bs["low"] = price
            bs["close"] = price
            bs["volume"] = volume
            bs["buy_vol"] = max(0, (volume + delta) / 2)
            bs["sell_vol"] = max(0, (volume - delta) / 2)
            bs["delta"] = delta
            bs["bar_time"] = bar_time
        else:
            if not bs["started"]:
                bs["open"] = price
                bs["bar_time"] = bar_time
                bs["started"] = True

            bs["high"] = max(bs["high"], price)
            bs["low"] = min(bs["low"], price)
            bs["close"] = price
            bs["volume"] += volume
            bs["delta"] += delta
            bs["buy_vol"] += max(0, (volume + delta) / 2)
            bs["sell_vol"] += max(0, (volume - delta) / 2)

        # Compute CVD slope
        cvd_list = self._cvd_bars.get(symbol, [])
        cvd_slope = self._compute_slope(cvd_list)

        # Compute aggression (simplified)
        aggression = self._compute_aggression(bs)

        return OneMinBarState(
            close=bs["close"],
            volume=bs["volume"],
            cvd_slope=cvd_slope,
            aggression=aggression,
            bar_time=bar_time,
            is_new_bar=is_new_bar,
        )

    @staticmethod
    def _compute_slope(values: list[float]) -> float:
        """Linear regression slope of CVD values."""
        n = len(values)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        den = sum((i - x_mean) ** 2 for i in range(n))
        return num / den if den > 0 else 0.0

    @staticmethod
    def _compute_aggression(bs: dict) -> float:
        """Simplified aggression score (0-4.5) for 1-min timeframe."""
        score = 0.0
        # Volume spike
        if bs["volume"] > 0:
            delta_pct = abs(bs["delta"]) / bs["volume"] if bs["volume"] > 0 else 0
            if delta_pct > 0.3:
                score += 1.5
            elif delta_pct > 0.15:
                score += 0.5
        # Directional bias
        if bs["delta"] > 0:
            score += 1.0
        elif bs["delta"] < 0:
            score += 1.0
        return min(score, 4.5)
