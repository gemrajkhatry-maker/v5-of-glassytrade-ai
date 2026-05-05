"""Microstructure analysis stage."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from typing import Any

from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import NormalizedTick, MicrostructureMetrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DepthState:
    symbol: str
    prev_top_bid: float
    prev_top_ask: float


class MicrostructureAnalysis:
    """Compute spread, imbalance, and depth-pressure metrics."""

    def __init__(self):
        self._state: dict[str, _DepthState] = {}
        self._last_tick_ts: dict[str, float] = {}
        self._metrics = StageMetrics(stage_name="MicrostructureAnalysis")

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def process(self, tick: NormalizedTick) -> list[MicrostructureMetrics]:
        try:
            is_depth = bool(getattr(tick, "is_depth", False))
            if not is_depth and not tick.bid and not tick.ask:
                bid = tick.price
                ask = tick.price
                spread = 0.0
            else:
                bid = tick.bid if tick.bid > 0 else tick.price
                ask = tick.ask if tick.ask > 0 else tick.price
                spread = max(0.0, ask - bid)

            spread_pct = spread / tick.price if tick.price else 0.0
            total_depth = tick.bid_volume + tick.ask_volume
            imbalance = ((tick.bid_volume - tick.ask_volume) / total_depth) if total_depth else 0.0
            depth_pressure = imbalance

            prev = self._state.get(tick.symbol)
            iceberg_detected = False
            stop_run_detected = False
            if prev is not None:
                iceberg_detected = abs(prev.prev_top_bid - bid) < 1e-12 and abs(prev.prev_top_ask - ask) < 1e-12
                stop_run_detected = (tick.price > prev.prev_top_ask) or (tick.price < prev.prev_top_bid)
            self._state[tick.symbol] = _DepthState(
                symbol=tick.symbol,
                prev_top_bid=bid,
                prev_top_ask=ask,
            )
            self._last_tick_ts[tick.symbol] = tick.timestamp

            self._metrics.record(0)
            return [MicrostructureMetrics(
                symbol=tick.symbol,
                timestamp=tick.timestamp,
                spread=spread,
                spread_pct=spread_pct,
                book_imbalance=imbalance,
                depth_pressure=depth_pressure,
                iceberg_detected=iceberg_detected,
                stop_run_detected=stop_run_detected,
                depth_available=is_depth or (tick.bid_volume + tick.ask_volume) > 0,
            )]
        except Exception:
            self._metrics.record_error()
            logger.exception("Microstructure analysis failed")
            return []

    def warmup(self) -> None:
        self._state = {}
        self._last_tick_ts = {}
        self._metrics.reset()

    def teardown(self) -> None:
        self.warmup()

    def reset(self) -> None:
        self.warmup()

    def snapshot(self) -> dict[str, Any]:
        state_payload: dict[str, dict[str, float]] = {
            symbol: {
                "symbol": state.symbol,
                "prev_top_bid": state.prev_top_bid,
                "prev_top_ask": state.prev_top_ask,
            }
            for symbol, state in self._state.items()
        }
        return {
            "state": state_payload,
            "last_tick_ts": dict(self._last_tick_ts),
        }

    def restore(self, payload: dict[str, Any]) -> None:
        self._state = {}
        self._last_tick_ts = {}
        if not isinstance(payload, dict):
            return
        state_payload = payload.get("state")
        if isinstance(state_payload, dict):
            for symbol, state in state_payload.items():
                if not isinstance(state, dict):
                    continue
                self._state[symbol] = _DepthState(
                    symbol=str(state.get("symbol", symbol)),
                    prev_top_bid=float(state.get("prev_top_bid", 0.0)),
                    prev_top_ask=float(state.get("prev_top_ask", 0.0)),
                )
        last_tick_ts = payload.get("last_tick_ts")
        if isinstance(last_tick_ts, dict):
            for symbol, ts in last_tick_ts.items():
                if not isinstance(symbol, str):
                    continue
                try:
                    self._last_tick_ts[symbol] = float(ts)
                except (TypeError, ValueError):
                    continue
