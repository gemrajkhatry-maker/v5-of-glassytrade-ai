"""Unit tests for Learning Engine domain service.

Ported from backend/tests/unit/domain/test_learning_engine.py.
"""

from __future__ import annotations

from quant.contracts.enums import Side, Source, PositionStatus
from quant.contracts.entities import Position
from quant.inference.models import ModelWeights
from quant.inference.learning_engine import LearningEngine


def _make_closed_trade(pnl: float, side: Side = Side.LONG, factor_bd: dict | None = None) -> Position:
    return Position(
        id="test", symbol="BTCUSDT", side=side, source=Source.PREDICTION,
        entry_price=100, size=1.0, stop_loss=95, take_profit=110,
        pnl=pnl, entry_time="t", status=PositionStatus.CLOSED,
        exit_price=110 if pnl > 0 else 95, exit_time="t",
        close_reason="Take Profit" if pnl > 0 else "Stop Loss",
        metadata={"factorBreakdown": factor_bd or {"trend": 50, "momentum": 20, "delta": 10, "order_book": 5}},
    )


class TestLearningEngine:
    def test_initial_weights(self):
        le = LearningEngine()
        w = le.weights
        total = w.trend + w.momentum + w.delta + w.order_book + w.volatility
        assert abs(total - 1.0) < 0.01

    def test_learn_from_win(self):
        le = LearningEngine()
        old_weights = le.weights
        trade = _make_closed_trade(pnl=100, factor_bd={"trend": 50, "momentum": 0, "delta": 0, "order_book": 0})
        le.learn(trade)
        new_weights = le.weights
        assert new_weights.trend != old_weights.trend
        assert le.generation == 1

    def test_learn_from_loss(self):
        le = LearningEngine()
        trade = _make_closed_trade(pnl=-100)
        le.learn(trade)
        assert le.generation == 1

    def test_ignores_non_prediction(self):
        le = LearningEngine()
        trade = Position(
            id="test", symbol="BTCUSDT", side=Side.LONG, source=Source.AMT,
            entry_price=100, size=1.0, stop_loss=95, take_profit=110,
            pnl=100, entry_time="t", status=PositionStatus.CLOSED,
        )
        le.learn(trade)
        assert le.generation == 0  # Not incremented

    def test_ignores_no_metadata(self):
        le = LearningEngine()
        trade = Position(
            id="test", symbol="BTCUSDT", side=Side.LONG, source=Source.PREDICTION,
            entry_price=100, size=1.0, stop_loss=95, take_profit=110,
            pnl=100, entry_time="t", status=PositionStatus.CLOSED,
        )
        le.learn(trade)
        assert le.generation == 0

    def test_weights_stay_normalized(self):
        le = LearningEngine()
        for i in range(20):
            trade = _make_closed_trade(
                pnl=100 if i % 2 == 0 else -100,
                factor_bd={"trend": 50 * (1 if i % 3 == 0 else -1), "momentum": 20, "delta": 10, "order_book": 5},
            )
            le.learn(trade)
        w = le.weights
        total = w.trend + w.momentum + w.delta + w.order_book + w.volatility
        assert abs(total - 1.0) < 0.05

    def test_multiple_generations(self):
        le = LearningEngine()
        for _ in range(5):
            le.learn(_make_closed_trade(pnl=50))
        assert le.generation == 5
