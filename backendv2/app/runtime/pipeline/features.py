"""Feature computation stage for deterministic signal input."""

from __future__ import annotations

import logging
from dataclasses import asdict
from collections import defaultdict, deque

from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import Candle, MarketStructureResult, OrderFlowMetrics, MicrostructureMetrics, FeatureVector

logger = logging.getLogger(__name__)


class FeatureComputation:
    """Compute VWAP/ATR/RSI-style features from candles and live context."""

    def __init__(self, max_candles: int = 200):
        self._max_candles = max_candles
        self._candles: dict[str, deque[Candle]] = defaultdict(lambda: deque(maxlen=max_candles))
        self._orderflow: dict[str, OrderFlowMetrics] = {}
        self._micro: dict[str, MicrostructureMetrics] = {}
        self._market: dict[str, MarketStructureResult] = {}
        self._metrics = StageMetrics(stage_name="FeatureComputation")

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def process(self, candle: Candle) -> list[FeatureVector]:
        try:
            symbol = candle.symbol
            self._candles[symbol].append(candle)
            candles = self._candles[symbol]
            if len(candles) < 2:
                return []

            closes = [c.close for c in candles]
            vols = [c.volume for c in candles]
            vwap = sum(p * v for p, v in zip(closes, vols, strict=False)) / (sum(vols) or 1.0)

            # Simple rolling stdev approximation for sigma bands
            mean = vwap
            variance = sum((p - mean) ** 2 for p in closes[-20:]) / max(1, min(len(closes), 20))
            stdev = variance ** 0.5

            if len(closes) >= 14:
                gains = []
                losses = []
                for i in range(1, min(len(closes), 15)):
                    diff = closes[-i] - closes[-i - 1]
                    gains.append(max(diff, 0.0))
                    losses.append(max(-diff, 0.0))
                avg_gain = sum(gains) / (len(gains) or 1)
                avg_loss = sum(losses) / (len(losses) or 1)
                rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
                rsi = 100 - (100 / (1 + rs))
            else:
                rsi = 50.0

            atr = max((max(closes[-14:]) - min(closes[-14:])), 1e-9) / 14 if len(closes) >= 14 else 0.0
            vol_window = vols[-20:]
            vol_avg = sum(vol_window) / len(vol_window) if vol_window else 0.0

            fv = FeatureVector(
                symbol=symbol,
                timestamp=candle.timestamp,
                vwap=float(vwap),
                vwap_upper_1sigma=float(mean + stdev),
                vwap_lower_1sigma=float(mean - stdev),
                vwap_upper_2sigma=float(mean + 2 * stdev),
                vwap_lower_2sigma=float(mean - 2 * stdev),
                atr_14=float(atr if atr > 0 else 0.0),
                rsi_14=float(rsi),
                rolling_volume_avg_20=float(vol_avg),
            )

            self._metrics.record(0)
            return [fv]
        except Exception:
            self._metrics.record_error()
            logger.exception("Feature computation failed")
            return []

    def ingest_orderflow(self, metric: OrderFlowMetrics) -> None:
        self._orderflow[metric.symbol] = metric

    def ingest_microstructure(self, metric: MicrostructureMetrics) -> None:
        self._micro[metric.symbol] = metric

    def ingest_market_structure(self, result: MarketStructureResult) -> None:
        self._market[result.symbol] = result

    def warmup(self) -> None:
        self._candles.clear()
        self._orderflow = {}
        self._micro = {}
        self._market = {}
        self._metrics.reset()

    def teardown(self) -> None:
        self.warmup()

    def reset(self) -> None:
        self.warmup()

    def snapshot(self) -> dict[str, object]:
        return {
            "max_candles": self._max_candles,
            "candles": {
                symbol: [asdict(candle) for candle in candles]
                for symbol, candles in self._candles.items()
            },
            "orderflow": {symbol: asdict(metric) for symbol, metric in self._orderflow.items()},
            "micro": {symbol: asdict(metric) for symbol, metric in self._micro.items()},
            "market": {symbol: asdict(result) for symbol, result in self._market.items()},
        }

    def restore(self, payload: dict[str, object]) -> None:
        self._candles.clear()
        self._orderflow = {}
        self._micro = {}
        self._market = {}

        if not isinstance(payload, dict):
            return

        max_candles = payload.get("max_candles")
        if isinstance(max_candles, int):
            self._max_candles = max_candles
            self._candles = defaultdict(lambda: deque(maxlen=max_candles))

        candles_payload = payload.get("candles")
        if isinstance(candles_payload, dict):
            for symbol, rows in candles_payload.items():
                if not isinstance(symbol, str) or not isinstance(rows, list):
                    continue
                for raw in rows:
                    if not isinstance(raw, dict):
                        continue
                    from app.runtime.pipeline import events
                    raw_timeframe = raw.get("timeframe", events.CandleTimeframe.M1.value)
                    if isinstance(raw_timeframe, events.CandleTimeframe):
                        timeframe = raw_timeframe
                    else:
                        timeframe = events.CandleTimeframe(raw_timeframe)
                    c = events.Candle(
                        **{**raw, "timeframe": timeframe},
                    )
                    self._candles[symbol].append(c)

        if isinstance(payload.get("orderflow"), dict):
            from app.runtime.pipeline import events
            for symbol, metric in payload["orderflow"].items():
                if isinstance(symbol, str) and isinstance(metric, dict):
                    try:
                        self._orderflow[symbol] = events.OrderFlowMetrics(**metric)
                    except TypeError:
                        continue

        if isinstance(payload.get("micro"), dict):
            from app.runtime.pipeline import events
            for symbol, metric in payload["micro"].items():
                if isinstance(symbol, str) and isinstance(metric, dict):
                    try:
                        self._micro[symbol] = events.MicrostructureMetrics(**metric)
                    except TypeError:
                        continue

        if isinstance(payload.get("market"), dict):
            from app.runtime.pipeline import events
            for symbol, result in payload["market"].items():
                if isinstance(symbol, str) and isinstance(result, dict):
                    try:
                        self._market[symbol] = events.MarketStructureResult(**result)
                    except TypeError:
                        continue
