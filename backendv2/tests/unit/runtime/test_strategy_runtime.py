"""Runtime strategy multiplexer contract tests."""

from app.runtime.pipeline.strategy import StrategyEvent, StrategyRuntime


class _Input:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol


def test_strategy_multiplexer_executes_multiple_strategies_with_priority() -> None:
    runtime = StrategyRuntime()
    input_event = _Input(symbol="BANKNIFTY")

    def first(_):
        return "first"

    def second(_):
        return ("second-a", "second-b")

    runtime.register("BANKNIFTY", strategy_id="alpha", handler=first, priority=10)
    runtime.register("BANKNIFTY", strategy_id="beta", handler=second, priority=0)

    events = runtime.process(input_event)
    assert len(events) == 3
    assert isinstance(events[0], StrategyEvent)
    assert isinstance(events[1], StrategyEvent)
    assert isinstance(events[2], StrategyEvent)
    assert [event.strategy_id for event in events] == ["beta", "beta", "alpha"]
    assert [event.payload for event in events] == ["second-a", "second-b", "first"]


def test_strategy_multiplexer_falls_back_to_identity_when_no_handler_output() -> None:
    runtime = StrategyRuntime()
    input_event = _Input(symbol="BANKNIFTY")

    def silent(_):
        return None

    runtime.register("BANKNIFTY", strategy_id="silent", handler=silent, priority=1)
    events = runtime.process(input_event)
    assert events == [input_event]


def test_strategy_snapshot_keeps_registration_contract() -> None:
    runtime = StrategyRuntime()

    def noop(_):
        return "ok"

    runtime.register("BANKNIFTY", strategy_id="core", handler=noop, priority=10)
    snapshot = runtime.snapshot()
    assert snapshot["registered_symbols"] == ["BANKNIFTY"]
    assert snapshot["bindings"]["BANKNIFTY"][0]["strategy_id"] == "core"
    assert snapshot["bindings"]["BANKNIFTY"][0]["priority"] == 10
