"""Signal generation stage."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import asdict
from typing import Any

from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import FeatureVector, MarketStructureResult, OrderFlowMetrics, MicrostructureMetrics, Signal

logger = logging.getLogger(__name__)


class SignalGeneration:
    """Wraps signal generation into one deterministic stage."""

    def __init__(
        self,
        ofi_long_threshold: float = 0.15,
        ofi_short_threshold: float = -0.30,
        min_confidence: float = 0.3,
        max_confidence: float = 0.95,
    ):
        self._last_feature: dict[str, FeatureVector] = {}
        self._last_orderflow: dict[str, OrderFlowMetrics] = {}
        self._last_micro: dict[str, MicrostructureMetrics] = {}
        self._last_market: dict[str, MarketStructureResult] = {}
        self._bars: dict[str, list[dict]] = defaultdict(list)
        self._metrics = StageMetrics(stage_name="SignalGeneration")
        self._ofi_long_threshold = ofi_long_threshold
        self._ofi_short_threshold = ofi_short_threshold
        self._min_confidence = min_confidence
        self._max_confidence = max_confidence

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def ingest(self, feature: FeatureVector) -> Signal | None:
        return self._build_signal(feature.symbol, feature)

    def process(self, feature: FeatureVector) -> list[Signal]:
        signal = self.ingest(feature)
        return [signal] if signal is not None else []

    def ingest_orderflow(self, metric: OrderFlowMetrics) -> None:
        self._last_orderflow[metric.symbol] = metric

    def ingest_microstructure(self, metric: MicrostructureMetrics) -> None:
        self._last_micro[metric.symbol] = metric

    def ingest_market_structure(self, result: MarketStructureResult) -> None:
        self._last_market[result.symbol] = result

    def _build_signal(self, symbol: str, feature: FeatureVector) -> Signal | None:
        try:
            ofi = self._last_orderflow.get(symbol)
            micro = self._last_micro.get(symbol)
            market = self._last_market.get(symbol)

            self._bars[symbol].append({
                "close": feature.vwap,
                "high": feature.vwap_upper_2sigma,
                "low": feature.vwap_lower_2sigma,
                "volume": max(feature.rolling_volume_avg_20, 1.0),
                "buyVolume": max((ofi.ofi if ofi else 0.0), 0.0),
                "sellVolume": max(-(ofi.ofi if ofi else 0.0), 0.0),
            })
            if len(self._bars[symbol]) > 200:
                self._bars[symbol] = self._bars[symbol][-200:]

            context_asl = market.ms_classifier_state if market else ""
            if market is not None:
                if market.market_state == "BEARISH" and feature.vwap_lower_2sigma > feature.vwap:
                    if ofi and ofi.ofi < self._ofi_short_threshold and (micro is None or not micro.iceberg_detected):
                        entry = feature.vwap
                        stop = feature.vwap_upper_2sigma
                        target = max(feature.vwap_lower_2sigma * 0.995, 0.0)
                        rr = abs(entry - target) / max(abs(stop - entry), 1e-9) if entry else 0.0
                        # Compute confidence from OFI magnitude
                        confidence = min(
                            self._max_confidence,
                            self._min_confidence + abs(ofi.ofi) * 0.6
                        )
                        self._metrics.record(0)
                        return Signal(
                            symbol=symbol, timestamp=feature.timestamp, type="SHORT", entry=entry,
                            sl=stop, tp=target, rr=rr, confidence=confidence, reason="Microstructure short",
                            source="pipeline", ofi=ofi.ofi if ofi else 0.0,
                        )

            # fallback: evaluate simplified long setup
            if ofi and ofi.ofi > self._ofi_long_threshold and feature.vwap_upper_1sigma >= feature.vwap and (micro is None or micro.depth_available):
                entry = feature.vwap
                stop = feature.vwap_lower_2sigma
                target = feature.vwap_upper_2sigma
                rr = abs(target - entry) / max(abs(entry - stop), 1e-9)
                # Compute confidence from OFI magnitude
                confidence = min(
                    self._max_confidence,
                    self._min_confidence + ofi.ofi * 0.6
                )
                self._metrics.record(0)
                return Signal(
                    symbol=symbol, timestamp=feature.timestamp, type="LONG", entry=entry,
                    sl=stop, tp=target, rr=rr, confidence=confidence, reason="Momentum long",
                    source="pipeline", ofi=ofi.ofi,
                )

            self._metrics.record(0)
            return Signal(
                symbol=symbol, timestamp=feature.timestamp, type="NO_TRADE", entry=0.0,
                sl=0.0, tp=0.0, rr=0.0, confidence=0.0, reason="No edge",
                source="pipeline", ofi=0.0,
            )
        except Exception:
            self._metrics.record_error()
            logger.exception("Signal generation failed")
            return None

    def warmup(self) -> None:
        self._last_feature = {}
        self._bars.clear()
        self._last_orderflow = {}
        self._last_micro = {}
        self._last_market = {}
        self._metrics.reset()

    def teardown(self) -> None:
        self.warmup()

    def reset(self) -> None:
        self.warmup()

    def snapshot(self) -> dict[str, Any]:
        return {
            "last_feature": {symbol: asdict(item) for symbol, item in self._last_feature.items()},
            "last_orderflow": {symbol: asdict(item) for symbol, item in self._last_orderflow.items()},
            "last_micro": {symbol: asdict(item) for symbol, item in self._last_micro.items()},
            "last_market": {symbol: asdict(item) for symbol, item in self._last_market.items()},
            "bars": self._bars,
        }

    def restore(self, payload: dict[str, Any]) -> None:
        self._last_feature = {}
        self._last_orderflow = {}
        self._last_micro = {}
        self._last_market = {}
        self._bars = defaultdict(list)

        if not isinstance(payload, dict):
            return

        from app.runtime.pipeline import events
        if isinstance(payload.get("last_feature"), dict):
            for symbol, value in payload["last_feature"].items():
                if isinstance(symbol, str) and isinstance(value, dict):
                    try:
                        self._last_feature[symbol] = events.FeatureVector(**value)
                    except TypeError:
                        continue

        if isinstance(payload.get("last_orderflow"), dict):
            for symbol, value in payload["last_orderflow"].items():
                if isinstance(symbol, str) and isinstance(value, dict):
                    try:
                        self._last_orderflow[symbol] = events.OrderFlowMetrics(**value)
                    except TypeError:
                        continue

        if isinstance(payload.get("last_micro"), dict):
            for symbol, value in payload["last_micro"].items():
                if isinstance(symbol, str) and isinstance(value, dict):
                    try:
                        self._last_micro[symbol] = events.MicrostructureMetrics(**value)
                    except TypeError:
                        continue

        if isinstance(payload.get("last_market"), dict):
            for symbol, value in payload["last_market"].items():
                if isinstance(symbol, str) and isinstance(value, dict):
                    try:
                        self._last_market[symbol] = events.MarketStructureResult(**value)
                    except TypeError:
                        continue

        bars_payload = payload.get("bars")
        if isinstance(bars_payload, dict):
            for symbol, bars in bars_payload.items():
                if isinstance(symbol, str) and isinstance(bars, list):
                    self._bars[symbol] = [entry for entry in bars if isinstance(entry, dict)]
