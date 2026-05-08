"""Explicit rejection and cancellation cleanup contract for rollback paths."""

from app.runtime.pipeline import events
from app.runtime.pipeline.events import FillEvent, PositionEvent, OrderStatusEvent, Signal
from app.runtime.orchestrator.session import SessionRuntime


class _RejectionExecution:
    def __init__(self, status: str):
        self._status = status

    def process(self, position_event: PositionEvent):
        return [
            events.OrderStatusEvent(
                order_id=position_event.position_id,
                symbol=position_event.symbol,
                status=self._status,
            )
        ]

    def snapshot(self):
        return {"broker_bound": True}

    def restore(self, payload):
        return None


def _base_signal() -> Signal:
    return Signal(
        symbol="BANKNIFTY",
        timestamp=1_000_000_000,
        type="LONG",
        entry=45010.0,
        sl=44900.0,
        tp=45200.0,
        rr=1.8,
        confidence=0.9,
        reason="rejection cleanup contract",
    )


def _assert_reject_path_cleans_state(runtime: SessionRuntime, status: str) -> None:
    runtime._execution = _RejectionExecution(status)

    runtime_events: list[object] = []
    runtime._run_signal_flow(_base_signal(), runtime_events)

    opened = [
        event
        for event in runtime_events
        if isinstance(event, PositionEvent) and event.event_type == "OPENED"
    ]
    assert opened, f"Expected OPENED position event for status={status}"
    open_event = opened[0]

    status_events = [
        event
        for event in runtime_events
        if isinstance(event, OrderStatusEvent)
        and event.order_id == open_event.position_id
        and event.symbol == open_event.symbol
    ]
    assert status_events and status_events[0].status == status

    fills = [
        event
        for event in runtime_events
        if isinstance(event, FillEvent)
        and event.order_id == open_event.position_id
    ]
    assert fills == []

    closes = [
        event
        for event in runtime_events
        if isinstance(event, PositionEvent)
        and event.event_type == "CLOSED"
        and event.position_id == open_event.position_id
    ]
    assert closes == []

    portfolio = runtime._position.get_portfolio("BANKNIFTY")
    assert not portfolio.has_open_positions()
    risk_snapshot = runtime._risk.snapshot()
    assert risk_snapshot["BANKNIFTY"]["portfolio"]["open_positions"] == []


def test_rejected_and_cancelled_paths_use_retract_cleanup_without_fill_close() -> None:
    for status in ("REJECTED", "CANCELLED"):
        runtime = SessionRuntime(feed=type("Feed", (), {
            "start": lambda self: None,
            "stop": lambda self: None,
            "stream": lambda self: iter([]),
            "name": lambda self: "unit-test-feed",
            "symbols": lambda self: ["BANKNIFTY"],
        })(), symbols=["BANKNIFTY"])
        _assert_reject_path_cleans_state(runtime, status)
    assert True  # Helper function contains assertions
