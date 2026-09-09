"""Single inference boundary for TimesFM-compatible forecasts."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from .contracts import ForecastSnapshot, ForecastStatus


class ForecastProvider:
    def __init__(self, model_loader: Callable[[], Any], horizon: int = 32) -> None:
        if horizon <= 0:
            raise ValueError("horizon must be positive")
        self._model_loader = model_loader
        self._horizon = horizon
        self._cache: dict[tuple[str, int], ForecastSnapshot] = {}

    def forecast(
        self,
        symbol: str,
        prices: Sequence[float],
        *,
        decision_sequence: int,
    ) -> ForecastSnapshot:
        key = (str(symbol), int(decision_sequence))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        if not prices:
            snapshot = ForecastSnapshot(
                symbol=str(symbol),
                decision_sequence=decision_sequence,
                status=ForecastStatus.INFERENCE_FAILED,
                failure_reason="forecast context is empty",
            )
            self._cache[key] = snapshot
            return snapshot
        try:
            model = self._model_loader()
            result = model.predict(
                context=np.asarray(prices, dtype=np.float32),
                horizon=self._horizon,
                return_quantiles=True,
            )
            quantiles = getattr(result, "quantiles", None)
            if quantiles is None or len(quantiles) == 0:
                raise RuntimeError("model returned no quantiles")
            p50 = np.asarray(quantiles)[:, 4]
            p10 = np.asarray(quantiles)[:, 0]
            p90 = np.asarray(quantiles)[:, 8]
            current = float(prices[-1])
            snapshot = ForecastSnapshot(
                symbol=str(symbol),
                decision_sequence=decision_sequence,
                status=ForecastStatus.AVAILABLE,
                model_version="timesfm",
                expected_return=float((p50[-1] - current) / max(abs(current), 1e-6)),
                dispersion=float(np.mean(p90 - p10)),
                velocity=float(p50[-1] - p50[0]),
            )
        except Exception as exc:
            snapshot = ForecastSnapshot(
                symbol=str(symbol),
                decision_sequence=decision_sequence,
                status=ForecastStatus.UNAVAILABLE,
                failure_reason=str(exc),
            )
        self._cache[key] = snapshot
        return snapshot
