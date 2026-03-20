"""Learning Engine — adaptive weight tuning domain service.

Implements a simplified 'backpropagation' loop that adjusts prediction model
weights based on trade outcomes, reinforcing factors that align with wins
and penalising those that align with losses.
"""

from __future__ import annotations

from app.domain.trading.models.enums import Side, Source
from app.domain.trading.models.entities import Position
from app.domain.fabio_ai.models.predictions import ModelWeights, FactorBreakdown


class LearningEngine:
    """Adaptive weight tuning engine.

    Adjusts weights of the PredictionEngine's scoring factors based on
    closed PREDICTION trades.
    """

    def __init__(self, learning_rate: float = 0.05) -> None:
        self._weights = {
            "trend": 0.40,
            "momentum": 0.25,
            "delta": 0.15,
            "order_book": 0.15,
            "volatility": 0.05,
        }
        self._learning_rate = learning_rate
        self._generation = 0
        self._history: list[dict] = []

    @property
    def weights(self) -> ModelWeights:
        return ModelWeights(**self._weights)

    @property
    def generation(self) -> int:
        return self._generation

    def learn(self, trade: Position) -> None:
        """Process a closed PREDICTION trade and adjust weights."""
        if trade.source != Source.PREDICTION:
            return
        if not trade.metadata or "factorBreakdown" not in trade.metadata:
            return

        raw = trade.metadata["factorBreakdown"]
        # raw may be a dict (from JSON) or already a FactorBreakdown
        if isinstance(raw, FactorBreakdown):
            bd = raw
        elif isinstance(raw, dict):
            bd = FactorBreakdown(**raw)
        else:
            return

        is_win = trade.pnl > 0
        trade_dir = 1 if trade.side == Side.LONG else -1

        self._adjust_factor(bd.trend, "trend", is_win, trade_dir)
        self._adjust_factor(bd.momentum, "momentum", is_win, trade_dir)
        self._adjust_factor(bd.delta, "delta", is_win, trade_dir)
        self._adjust_factor(bd.order_book, "order_book", is_win, trade_dir)

        self._normalize()
        self._generation += 1

        self._history.append({
            "generation": self._generation,
            "result": "WIN" if is_win else "LOSS",
            "weights": dict(self._weights),
        })

    def _adjust_factor(
        self, factor_score: float, key: str, is_win: bool, trade_dir: int
    ) -> None:
        if factor_score == 0:
            return

        factor_dir = 1 if factor_score > 0 else -1
        agreed = factor_dir == trade_dir

        if is_win:
            if agreed:
                self._weights[key] += self._learning_rate
            else:
                self._weights[key] -= self._learning_rate * 0.5
        else:
            if agreed:
                self._weights[key] -= self._learning_rate
            else:
                self._weights[key] += self._learning_rate * 0.5

    def _normalize(self) -> None:
        total = sum(abs(v) for v in self._weights.values())
        if total == 0:
            return
        for key in self._weights:
            self._weights[key] = max(0.01, self._weights[key] / total)
