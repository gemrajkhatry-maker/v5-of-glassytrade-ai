# tests/quant/test_strategy.py
"""Strategy seam: the engine resolves a pluggable decision policy.

The engine (and backend bridge) own the loop/risk/OMS/exits; the strategy only
answers ``evaluate(ctx) -> QuantDecision``. These tests prove the default AMT
policy is wired, that the registry is the single switch point, and that a custom
strategy plugs in without touching the engine.
"""

import pytest

from quant.brokers.synthetic import SyntheticGateway
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService, QuantDecision
from quant.events import PositionOpened, SignalApproved
from quant.runtime import QuantEngine
from quant.strategy import (
    DEFAULT_STRATEGY,
    Strategy,
    get_strategy,
    register_strategy,
)


def _tick_list():
    # Reuse the runtime fixture: quiet bars, absorption spike, rising breakout.
    from tests.quant.runtime.test_runtime import _ticks

    return _ticks()


def test_default_strategy_is_the_amt_decision_service():
    strategy = get_strategy()
    assert isinstance(strategy, Strategy)
    assert strategy.name == "amt"
    assert isinstance(strategy, DecisionService)
    assert DEFAULT_STRATEGY == "amt"


def test_get_strategy_forwards_kwargs_to_factory():
    strategy = get_strategy(min_rr=3.0)
    assert strategy.min_rr == 3.0


def test_unknown_strategy_raises_clear_error():
    with pytest.raises(KeyError) as exc:
        get_strategy("does_not_exist")
    assert "does_not_exist" in str(exc.value)
    assert "amt" in str(exc.value)  # registered names listed in the error


def test_engine_defaults_to_amt_strategy():
    eng = QuantEngine(SyntheticGateway(_tick_list()), "SYM", interval_seconds=1)
    assert isinstance(eng._strategy, DecisionService)


class _FixedStrategy:
    """Duck-typed strategy: returns a canned approved LONG."""

    name = "fixed"

    def __init__(self, signal) -> None:
        self._signal = signal

    def evaluate(self, ctx: DecisionContext) -> QuantDecision:
        return QuantDecision(True, self._signal, "Triple-A", "AGGRESSION", ())


def test_engine_uses_injected_strategy():
    from quant.contracts.entities import Signal
    from quant.contracts.enums import SetupType, SignalType, Source

    canned = Signal.create(
        type=SignalType.BUY,
        price=100.0,
        reason="canned",
        stop_loss=99.0,
        take_profit=102.0,
        timestamp="t",
        setup=SetupType.TREND_MODEL,
        source=Source.LLM,
        metadata={"quant_rr": 2.0, "confidence": 0.7},
    )
    eng = QuantEngine(
        SyntheticGateway(_tick_list()), "SYM", interval_seconds=1,
        stream_id="strategy:SYM", strategy=_FixedStrategy(canned),
    )
    trace = eng.run()
    approved = [e for e in trace if isinstance(e, SignalApproved)]
    assert approved, "injected strategy should emit approved signals"
    assert all(e.signal.reason == "canned" for e in approved)
    assert any(isinstance(e, PositionOpened) for e in trace)


def test_custom_strategy_registry_round_trip():
    """register_strategy + get_strategy is the live-swap mechanism."""

    class OtherStrategy:
        name = "other"

        def __init__(self, **kwargs):
            pass

        def evaluate(self, ctx):
            return QuantDecision(False, None, "NO_EDGE", "", ())

    register_strategy("other", OtherStrategy)
    try:
        assert isinstance(get_strategy("other"), OtherStrategy)
    finally:
        # leave the global registry clean for other tests
        from quant.strategy import _STRATEGIES

        _STRATEGIES.pop("other", None)
