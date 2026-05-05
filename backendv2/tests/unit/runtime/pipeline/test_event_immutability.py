"""Runtime immutability checks for event contracts."""

import pytest
from dataclasses import FrozenInstanceError
import copy

from app.runtime.pipeline.events import (
    FillEvent,
    FeatureVector,
    GateResult,
    OrderStatusEvent,
    MarketStructureResult,
    PositionEvent,
    GateResultType,
    RiskResult,
    Signal,
)
from app.runtime.pipeline.strategy import StrategyEvent, StrategyRuntime


@pytest.mark.parametrize(
    "event",
    [
        Signal(
            symbol="BANKNIFTY",
            timestamp=0.0,
            type="LONG",
            entry=45000.0,
            sl=44500.0,
            tp=45500.0,
            rr=1.2,
            confidence=0.7,
            reason="immutability",
        ),
        MarketStructureResult(symbol="BANKNIFTY", timestamp=0.0, poc=0.0, vah=0.0, val=0.0),
        GateResult(
            symbol="BANKNIFTY",
            timestamp=0.0,
            signal=Signal(
                symbol="BANKNIFTY",
                timestamp=0.0,
                type="NO_TRADE",
                entry=0.0,
                sl=0.0,
                tp=0.0,
                rr=0.0,
                confidence=0.0,
                reason="no-trade",
            ),
            result=GateResultType.APPROVED,
        ),
        RiskResult(
            symbol="BANKNIFTY",
            timestamp=0.0,
            approved=True,
            remaining_buying_power=0.0,
        ),
        PositionEvent(
            symbol="BANKNIFTY",
            timestamp=0.0,
            event_type="OPENED",
            position_id="x",
        ),
        FeatureVector(
            symbol="BANKNIFTY",
            timestamp=0.0,
            vwap=45000.0,
            vwap_upper_1sigma=45100.0,
            vwap_lower_1sigma=44900.0,
            vwap_upper_2sigma=45200.0,
            vwap_lower_2sigma=44800.0,
            atr_14=100.0,
        ),
        FillEvent(
            order_id="x",
            symbol="BANKNIFTY",
            side="BUY",
            quantity=1.0,
            price=45000.0,
            timestamp=0.0,
        ),
    ],
)
def test_events_are_frozen(event) -> None:
    with pytest.raises(FrozenInstanceError):
        event.symbol = "NIFTY"


@pytest.mark.parametrize(
    "event",
    [
        OrderStatusEvent(
            order_id="x",
            symbol="BANKNIFTY",
            status="FILLED",
            filled_quantity=1.0,
        ),
        PositionEvent(
            symbol="BANKNIFTY",
            timestamp=0.0,
            event_type="OPENED",
            position_id="p1",
        ),
        RiskResult(
            symbol="BANKNIFTY",
            timestamp=0.0,
            approved=True,
            rejection_reason="",
            remaining_buying_power=10000.0,
        ),
    ],
)
def test_composite_events_are_frozen(event) -> None:
    with pytest.raises(FrozenInstanceError):
        event.symbol = "NIFTY"


def test_strategy_event_payload_is_decoupled_from_handler_output() -> None:
    runtime = StrategyRuntime()
    payload = {"flags": {"active": True}, "values": [1, 2, 3]}

    class _Input:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

    def _strategy_handler(_input: _Input) -> dict[str, object]:
        return payload

    runtime.register("BANKNIFTY", strategy_id="immutability_guard", handler=_strategy_handler)
    events = runtime.process(_Input("BANKNIFTY"))

    assert len(events) == 1
    runtime_event = events[0]
    assert isinstance(runtime_event, StrategyEvent)
    runtime_payload = runtime_event.payload
    assert runtime_payload == payload
    assert runtime_payload is not payload

    payload["values"].append(99)
    assert runtime_payload["values"] == [1, 2, 3]
