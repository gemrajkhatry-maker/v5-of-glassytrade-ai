"""Order flow pipeline stage."""

from __future__ import annotations

import logging
from collections import deque, defaultdict
from dataclasses import dataclass
from typing import Optional

from app.domain.amt.service.cvd_tracker import CVDTracker
from app.domain.amt.service.orderflow_detectors import BigTradeDetector, calculate_ofi
from app.domain.amt.service.footprint_analyzer import TickFootprintAccumulator
from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import NormalizedTick, OrderFlowMetrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _OrderFlowState:
    cvd: CVDTracker
    big_trade: BigTradeDetector
    volumes: deque[float]
    footprint: TickFootprintAccumulator


class OrderFlowPipeline:
    """Compute tick-level order-flow metrics."""

    def __init__(self, max_history: int = 200):
        self._states: dict[str, _OrderFlowState] = {}
        self._window = max_history
        self._tick_index: dict[str, int] = defaultdict(int)
        self._metrics = StageMetrics(stage_name="OrderFlowPipeline")

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def _state(self, symbol: str) -> _OrderFlowState:
        if symbol not in self._states:
            self._states[symbol] = _OrderFlowState(
                cvd=CVDTracker(max_history=self._window),
                big_trade=BigTradeDetector(),
                volumes=deque(maxlen=self._window),
                footprint=TickFootprintAccumulator(),
            )
        return self._states[symbol]

    @staticmethod
    def _candle_time_ns(timestamp: float) -> str:
        ts = float(timestamp)
        if ts < 1_000_000_000_000:
            ts *= 1_000_000_000
        return str(int(ts // 60_000_000_000))

    def process(self, tick: NormalizedTick) -> list[OrderFlowMetrics]:
        try:
            if tick.volume <= 0:
                return []
            state = self._state(tick.symbol)
            idx = self._tick_index[tick.symbol]
            self._tick_index[tick.symbol] = idx + 1

            state.volumes.append(tick.volume)
            state.big_trade.update_avg_volume(tick.volume)

            point = state.cvd.update(
                bar_index=idx,
                bid_volume=tick.bid_volume,
                ask_volume=tick.ask_volume,
                price=tick.price,
            )
            big_trade = state.big_trade.detect(tick.price, tick.volume, idx)
            absorption = False
            absorption_side = "NONE"
            window: list[float] = list(state.volumes)
            average_volume = sum(window) / len(window) if window else tick.volume
            if state.cvd.cumulative_delta != 0 and state.volumes:
                if len(window) >= 20:
                    mean_vol = sum(window[:-1]) / (len(window) - 1) if len(window) > 1 else tick.volume
                    if mean_vol > 0 and tick.volume >= mean_vol * 2.5:
                        absorption = True
                        absorption_side = "BUY" if tick.bid_volume >= tick.ask_volume else "SELL"
                    average_volume = mean_vol

            bar = {
                "buyVolume": tick.bid_volume,
                "sellVolume": tick.ask_volume,
                "close": tick.price,
                "volume": tick.volume,
            }
            ofi = calculate_ofi(bar)
            big_trades = 1 if big_trade else 0
            candle_time = self._candle_time_ns(tick.timestamp)
            state.footprint.on_tick(
                ltp=float(tick.price),
                ltq=int(tick.volume),
                best_bid=float(tick.bid),
                best_ask=float(tick.ask),
                candle_time=candle_time,
            )
            stacked_imbalance = False
            latest_candle = state.footprint.get_all().get(candle_time)
            if latest_candle is not None:
                stacked_imbalance = any(
                    level.stacked for level in latest_candle.levels
                )

            self._metrics.record(0)
            return [OrderFlowMetrics(
                symbol=tick.symbol,
                timestamp=tick.timestamp,
                cumulative_delta=point.cumulative_delta,
                bid_volume=tick.bid_volume,
                ask_volume=tick.ask_volume,
                ofi=ofi,
                big_trades=big_trades,
                volume_bubble=tick.volume > average_volume,
                absorption_detected=absorption,
                absorption_side=absorption_side,
                absorption_strength=min(1.0, tick.volume / max(state.volumes) if state.volumes else 1.0),
                stacked_imbalance=stacked_imbalance,
                window_size=self._window,
            )]
        except Exception:
            self._metrics.record_error()
            logger.exception("OrderFlow processing failed")
            return []

    def warmup(self) -> None:
        self._states = {}
        self._tick_index = defaultdict(int)
        self._metrics.reset()

    def teardown(self) -> None:
        self.warmup()

    def reset(self) -> None:
        self.warmup()

    def snapshot(self) -> dict[str, object]:
        states: dict[str, object] = {}
        for symbol, state in self._states.items():
            states[symbol] = {
                "cvd": state.cvd.__dict__.copy(),
                "big_trade": state.big_trade.__dict__.copy(),
                "volumes": list(state.volumes),
                "footprint": len(state.footprint.get_all()),
            }
        return {
            "states": states,
            "tick_index": dict(self._tick_index),
            "window": self._window,
        }

    def restore(self, payload: dict[str, object]) -> None:
        self._states = {}
        if not isinstance(payload, dict):
            return
        self._tick_index = defaultdict(int)
        if isinstance(payload.get("tick_index"), dict):
            for symbol, value in payload["tick_index"].items():
                if isinstance(symbol, str) and isinstance(value, int):
                    self._tick_index[symbol] = value
                elif isinstance(symbol, str) and isinstance(value, str):
                    try:
                        self._tick_index[symbol] = int(value)
                    except ValueError:
                        continue
        window = payload.get("window")
        if isinstance(window, int):
            self._window = window
        states = payload.get("states", {})
        if isinstance(states, dict):
            for symbol, state_payload in states.items():
                if not isinstance(state_payload, dict):
                    continue
                cvd_payload = state_payload.get("cvd")
                big_payload = state_payload.get("big_trade")
                volumes_payload = state_payload.get("volumes")
                cvd = CVDTracker(max_history=self._window)
                if isinstance(cvd_payload, dict):
                    for key, value in cvd_payload.items():
                        cvd.__dict__[key] = value
                big = BigTradeDetector()
                if isinstance(big_payload, dict):
                    for key, value in big_payload.items():
                        big.__dict__[key] = value
                volumes = deque(maxlen=self._window)
                if isinstance(volumes_payload, list):
                    for raw_value in volumes_payload:
                        try:
                            volumes.append(float(raw_value))
                        except (TypeError, ValueError):
                            continue
                self._states[symbol] = _OrderFlowState(
                    cvd=cvd,
                    big_trade=big,
                    volumes=volumes,
                    footprint=TickFootprintAccumulator(),
                )
