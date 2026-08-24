"""Strategy lifecycle + config-driven instantiation (P1b).

``ReactiveStrategyEngine.register`` must invoke the strategy's ``on_start``
hook and ``unregister``/``dispose_all`` its ``on_stop`` hook (the hooks existed
on the protocol but were never called). ``StrategySpec`` + ``build_strategy``
reuse one strategy class across instruments/parameter sets without code
changes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tradex_domain.enums import OrderSide, OrderType, TimeInForce
from tradex_domain.instruments import Equity
from tradex_domain.strategy import Signal
from tradex_domain.value_objects import Price, Quantity

from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.strategy.core.engine import ReactiveStrategyEngine
from tradex_trading.strategy.core.factory import StrategySpec, build_strategy


def _eq() -> Equity:
    return Equity.of("NSE", "RELIANCE")


class _LifecycleProbe:
    """Records lifecycle hook invocations and exposes a configurable param."""

    strategy_id = "probe"

    def __init__(self, strategy_id: str, instrument, *, period: int = 1) -> None:
        self.strategy_id = strategy_id
        self.instrument = instrument
        self.period = period
        self.started = 0
        self.stopped = 0
        self.version = "1.0.0"
        self.signals: list[Signal] = []

    def on_start(self, context) -> None:
        self.started += 1

    def on_stop(self, context) -> None:
        self.stopped += 1

    def on_bar(self, context, candle) -> Signal | None:
        return None

    def on_quote(self, context, quote) -> Signal | None:
        return None

    def on_depth(self, context, depth) -> Signal | None:
        return None

    def on_fill(self, context, fill) -> None:
        pass


def test_register_calls_on_start() -> None:
    engine = ReactiveStrategyEngine(ReactiveBus())
    strategy = _LifecycleProbe("p-1", _eq())
    engine.register(strategy)
    try:
        assert strategy.started == 1
    finally:
        engine.dispose_all()


def test_unregister_calls_on_stop() -> None:
    engine = ReactiveStrategyEngine(ReactiveBus())
    strategy = _LifecycleProbe("p-2", _eq())
    engine.register(strategy)
    engine.unregister("p-2")
    assert strategy.started == 1
    assert strategy.stopped == 1
    engine.dispose_all()


def test_dispose_all_stops_every_strategy() -> None:
    engine = ReactiveStrategyEngine(ReactiveBus())
    a = _LifecycleProbe("p-a", _eq())
    b = _LifecycleProbe("p-b", _eq())
    engine.register(a)
    engine.register(b)
    engine.dispose_all()
    assert a.stopped == 1
    assert b.stopped == 1


def test_duplicate_register_raises() -> None:
    engine = ReactiveStrategyEngine(ReactiveBus())
    engine.register(_LifecycleProbe("dup", _eq()))
    try:
        with pytest.raises(ValueError, match="already registered"):
            engine.register(_LifecycleProbe("dup", _eq()))
    finally:
        engine.dispose_all()


def test_build_strategy_applies_params() -> None:
    spec = StrategySpec(
        strategy_class=_LifecycleProbe,
        strategy_id="cfg-1",
        instrument=_eq(),
        params={"period": 7},
    )
    strategy = build_strategy(spec)
    assert strategy.strategy_id == "cfg-1"
    assert strategy.period == 7


def test_register_spec_builds_and_starts() -> None:
    engine = ReactiveStrategyEngine(ReactiveBus())
    spec = StrategySpec(
        strategy_class=_LifecycleProbe,
        strategy_id="spec-1",
        instrument=_eq(),
        params={"period": 3},
    )
    try:
        strategy = engine.register_spec(spec)
        assert strategy.period == 3
        assert strategy.started == 1
        assert "spec-1" in engine._strategies  # noqa: SLF001 – probe internal state
    finally:
        engine.dispose_all()
