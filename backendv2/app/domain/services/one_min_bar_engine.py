"""1-minute bar aggregation engine for MTF scalp support."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from app.domain.trading.model.value_objects import OHLC

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OneMinBarState:
    close: float
    volume: float
    cvd_slope: float
    aggression: float
    bar_time: str
    is_new_bar: bool


class OneMinBarEngine:
    """Build 1-min bars from ticks for low-latency scalp checks."""

    def __init__(self, cvd_window: int = 10) -> None:
        self._cvd_window = cvd_window
        self._bar_states: dict[str, dict] = {}
        self._cvd_bars: dict[str, list[float]] = {}

    def _get_bar_state(self, symbol: str) -> dict:
        if symbol not in self._bar_states:
            self._bar_states[symbol] = {
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "close": 0.0,
                "volume": 0.0,
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
        bs = self._get_bar_state(symbol)
        try:
            dt = datetime.fromisoformat(timestamp)
            bar_minute = dt.replace(second=0, microsecond=0)
            bar_time = bar_minute.isoformat()
        except (TypeError, ValueError):
            bar_time = timestamp

        is_new_bar = bar_time != bs["bar_time"]
        if is_new_bar and bs["started"]:
            cvd_list = self._cvd_bars[symbol]
            cvd_list.append(bs["delta"])
            if len(cvd_list) > self._cvd_window:
                cvd_list.pop(0)

            bs["open"] = price
            bs["high"] = price
            bs["low"] = price
            bs["close"] = price
            bs["volume"] = volume
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

        cvd_slope = self._compute_slope(self._cvd_bars.get(symbol, []))
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
        n = len(values)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        return numerator / denominator if denominator > 0 else 0.0

    @staticmethod
    def _compute_aggression(state: dict) -> float:
        score = 0.0
        if state["volume"] > 0:
            delta_pct = abs(state["delta"]) / state["volume"] if state["volume"] else 0.0
            if delta_pct > 0.3:
                score += 1.5
            elif delta_pct > 0.15:
                score += 0.5
        if state["delta"] > 0:
            score += 1.0
        elif state["delta"] < 0:
            score += 1.0
        return min(score, 4.5)

