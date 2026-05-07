"""Runtime test enforcing stage-coupling order around the critical path."""

from app.runtime.feeds import LiveFeed
from app.runtime.pipeline.events import OrderStatusEvent, FillEvent
from app.runtime.pipeline.events import (
    GateResult,
    PositionEvent,
    RiskResult,
    Signal,
    Tick,
)
from app.runtime.pipeline.strategy import StrategyEvent
from app.runtime.orchestrator.session import SessionRuntime
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter


def _make_data() -> list[dict]:
    return [
        {
            "symbol": "BANKNIFTY",
            "timestamp": float(i * 1_000_000_000),
            "price": 45000.0 + i * 0.25,
            "volume": 100.0,
            "bid": 44999.5 + i * 0.25,
            "ask": 45000.5 + i * 0.25,
            "bid_volume": 50.0,
            "ask_volume": 50.0,
        }
        for i in range(130)
    ]


def _to_ticks(rows: list[dict]) -> list[Tick]:
    return [
        Tick(
            symbol=row["symbol"],
            timestamp=float(row["timestamp"]),
            price=float(row["price"]),
            volume=float(row["volume"]),
            bid=float(row["bid"]),
            ask=float(row["ask"]),
            bid_volume=float(row.get("bid_volume", 0.0)),
            ask_volume=float(row.get("ask_volume", 0.0)),
        )
        for row in rows
    ]


def _live_runtime(rows: list[dict], symbols: list[str]) -> SessionRuntime:
    runtime = SessionRuntime(
        feed=LiveFeed(symbols=symbols, tick_source=_to_ticks(rows), strict_symbol_mode=True),
        symbols=symbols,
    )
    runtime.bind_broker(PaperBrokerAdapter())
    return runtime


def _strategy_signal_from_feature(feature: object) -> Signal:
    return Signal(
        symbol=getattr(feature, "symbol"),
        timestamp=getattr(feature, "timestamp"),
        type="LONG",
        entry=float(getattr(feature, "vwap")),
        sl=float(getattr(feature, "vwap") * 0.985),
        tp=float(getattr(feature, "vwap") * 1.03),
        rr=2.0,
        confidence=0.88,
        reason="stage-order test strategy",
        source="strategy",
    )


def test_pipeline_edge_order_enforced_for_approved_strategy_chain() -> None:
    runtime = _live_runtime(_make_data(), symbols=["BANKNIFTY"])
    runtime.register_strategy(
        symbol="BANKNIFTY",
        strategy_id="stage_order_guard",
        handler=_strategy_signal_from_feature,
        priority=1,
    )
    runtime.start()
    events = runtime.run_once(max_ticks=130)

    opened_positions = [
        (index, event)
        for index, event in enumerate(events)
        if isinstance(event, PositionEvent) and event.event_type == "OPENED"
    ]
    assert opened_positions, "Expected a strategy-driven position open event"

    open_index, open_event = opened_positions[0]
    strategy_symbol = open_event.symbol

    strategy_index = next(
        (
            index
            for index, event in enumerate(events)
            if isinstance(event, StrategyEvent)
            and isinstance(event.payload, Signal)
            and event.payload.symbol == strategy_symbol
            and event.payload.timestamp == open_event.timestamp
        ),
        -1,
    )
    assert strategy_index >= 0
    assert strategy_index < open_index

    signal_index = next(
        (
            index
            for index, event in enumerate(events)
            if isinstance(event, Signal)
            and event.symbol == strategy_symbol
            and event.timestamp == open_event.timestamp
        ),
        -1,
    )
    assert signal_index > strategy_index
    assert signal_index < open_index

    gate_index = next(
        (
            index
            for index, event in enumerate(events)
            if isinstance(event, GateResult)
            and event.symbol == strategy_symbol
            and event.signal.timestamp == open_event.timestamp
        ),
        -1,
    )
    assert gate_index > signal_index
    assert gate_index < open_index

    risk_index = next(
        (
            index
            for index, event in enumerate(events)
            if isinstance(event, RiskResult)
            and event.symbol == strategy_symbol
            and event.timestamp == open_event.timestamp
        ),
        -1,
    )
    assert risk_index > gate_index
    assert risk_index < open_index

    order_index = next(
        (
            index
            for index, event in enumerate(events)
            if isinstance(event, OrderStatusEvent)
            and event.order_id == open_event.position_id
        ),
        -1,
    )
    assert order_index > risk_index, "Order status must follow RiskResult"
    assert order_index > open_index, "Order status must follow OPENED position event"

    fill_index = next(
        (
            index
            for index, event in enumerate(events)
            if isinstance(event, FillEvent)
            and event.order_id == open_event.position_id
        ),
        -1,
    )
    assert fill_index > order_index, "Fill event must follow order status"

    close_index = next(
        (
            index
            for index, event in enumerate(events)
            if isinstance(event, PositionEvent)
            and event.event_type == "CLOSED"
            and event.position_id == open_event.position_id
        ),
        -1,
    )
    assert close_index > fill_index, "Closed event should follow immediate fill for strategy position"


class _ExecutionEmulator:
    """Deterministic execution stage stub for rejected/cancelled branches."""

    def __init__(self, status: str):
        self.status = status

    def process(self, position_event: PositionEvent):
        return [
            OrderStatusEvent(
                order_id=position_event.position_id,
                symbol=position_event.symbol,
                status=self.status,
            )
        ]

    def snapshot(self) -> dict[str, object]:
        return {"broker_bound": True}

    def restore(self, payload: dict[str, object]) -> None:
        return None


class _EmptyExecution:
    """Simulate no order-status envelope returned by broker bridge."""

    def process(self, position_event: PositionEvent):
        return []

    def snapshot(self) -> dict[str, object]:
        return {"broker_bound": True}

    def restore(self, payload: dict[str, object]) -> None:
        return None


class _MultiStatusExecution:
    """Simulate mixed terminal/non-terminal execution status vectors."""

    def process(self, position_event: PositionEvent):
        return [
            OrderStatusEvent(
                order_id=position_event.position_id,
                symbol=position_event.symbol,
                status="PENDING",
            ),
            OrderStatusEvent(
                order_id=position_event.position_id,
                symbol=position_event.symbol,
                status="FILLED",
            ),
        ]

    def snapshot(self) -> dict[str, object]:
        return {"broker_bound": True}

    def restore(self, payload: dict[str, object]) -> None:
        return None


class _FillOnlyBrokerSync:
    """Return fills only for explicit FILLED statuses."""

    def process(self, order_status: OrderStatusEvent):
        if order_status.status != "FILLED":
            return []
        return [
            FillEvent(
                order_id=order_status.order_id,
                symbol=order_status.symbol,
                side="BUY",
                quantity=float("inf"),
                price=45000.0,
                timestamp=order_status.timestamp,
            )
        ]

    def snapshot(self) -> dict[str, object]:
        return {}

    def restore(self, payload: dict[str, object]) -> None:
        return None


def _make_rejected_signal() -> Signal:
    return Signal(
        symbol="BANKNIFTY",
        timestamp=1_000_000_000,
        type="LONG",
        entry=45005.0,
        sl=44850.0,
        tp=45180.0,
        rr=2.0,
        confidence=0.95,
        reason="stage-order reject contract",
    )


def test_pipeline_edge_order_for_reject_and_cancel_branches() -> None:
    for status in ("REJECTED", "CANCELLED"):
        runtime = _live_runtime(_make_data(), symbols=["BANKNIFTY"])
        runtime._execution = _ExecutionEmulator(status)
        events: list[object] = []
        runtime._run_signal_flow(_make_rejected_signal(), events)

        opened = [event for event in events if isinstance(event, PositionEvent) and event.event_type == "OPENED"]
        assert opened, f"Expected OPENED position for status={status}"
        open_event = opened[0]

        order_events = [
            event
            for event in events
            if isinstance(event, OrderStatusEvent)
            and event.order_id == open_event.position_id
            and event.symbol == open_event.symbol
        ]
        assert order_events, f"Expected broker status event for status={status}"
        assert order_events[0].status == status
        order_index = events.index(order_events[0])
        open_index = events.index(open_event)
        assert order_index > open_index

        assert all(
            not isinstance(event, FillEvent)
            for event in events[order_index:]
        ), "Reject/cancel path must never emit FillEvent"

        closed = [
            event
            for event in events
            if isinstance(event, PositionEvent)
            and event.event_type == "CLOSED"
            and event.position_id == open_event.position_id
        ]
        assert not closed, f"Reject/cancel path must not emit PositionEvent.CLOSED for order_id={open_event.position_id}"

        runtime_portfolio = runtime._position.get_portfolio("BANKNIFTY")
        assert not runtime_portfolio.has_open_positions()
        risk_snapshot = runtime._risk.snapshot()
        assert risk_snapshot["BANKNIFTY"]["portfolio"]["open_positions"] == []


def test_pipeline_handles_empty_execution_vector_as_rejection() -> None:
    runtime = _live_runtime(_make_data(), symbols=["BANKNIFTY"])
    runtime._execution = _EmptyExecution()
    events: list[object] = []
    runtime._run_signal_flow(_make_rejected_signal(), events)

    opened = [event for event in events if isinstance(event, PositionEvent) and event.event_type == "OPENED"]
    assert opened, "Expected OPENED position for empty execution path"
    open_event = opened[0]

    order_events = [
        event
        for event in events
        if isinstance(event, OrderStatusEvent)
        and event.order_id == open_event.position_id
        and event.symbol == open_event.symbol
    ]
    assert order_events, "Expected synthetic rejection status when execution returns no status events"
    assert order_events[0].status == "REJECTED"

    runtime_portfolio = runtime._position.get_portfolio("BANKNIFTY")
    assert not runtime_portfolio.has_open_positions()
    risk_snapshot = runtime._risk.snapshot()
    assert risk_snapshot["BANKNIFTY"]["portfolio"]["open_positions"] == []


def test_pipeline_accepts_multi_status_execution_vector_and_preserves_fill_order() -> None:
    runtime = _live_runtime(_make_data(), symbols=["BANKNIFTY"])
    runtime._execution = _MultiStatusExecution()
    runtime._broker_sync = _FillOnlyBrokerSync()
    events: list[object] = []
    runtime._run_signal_flow(_make_rejected_signal(), events)

    open_event = next(
        (
            event
            for event in events
            if isinstance(event, PositionEvent) and event.event_type == "OPENED"
        ),
        None,
    )
    assert open_event is not None

    order_events = [
        event
        for event in events
        if isinstance(event, OrderStatusEvent)
        and event.order_id == open_event.position_id
        and event.symbol == open_event.symbol
    ]
    assert len(order_events) == 2
    assert order_events[0].status == "PENDING"
    assert order_events[1].status == "FILLED"

    fill_index = events.index(next(
        event for event in events
        if isinstance(event, FillEvent) and event.order_id == open_event.position_id
    ))
    assert fill_index > events.index(order_events[1])

    close_index = events.index(
        next(
            event
            for event in events
            if isinstance(event, PositionEvent)
            and event.event_type == "CLOSED"
            and event.position_id == open_event.position_id
        )
    )
    assert close_index > fill_index


def _interleave_data() -> list[dict]:
    return [
        {
            "symbol": "BANKNIFTY",
            "timestamp": float(i * 1_000_000_000),
            "price": 45000.0 + i,
            "volume": 100.0,
            "bid": 44999.0 + i,
            "ask": 45001.0 + i,
            "bid_volume": 50.0,
            "ask_volume": 50.0,
        }
        if i % 2 == 0
        else {
            "symbol": "FINNIFTY",
            "timestamp": float(i * 1_000_000_000 + 250_000_000),
            "price": 18500.0 + i,
            "volume": 100.0,
            "bid": 18499.0 + i,
            "ask": 18501.0 + i,
            "bid_volume": 50.0,
            "ask_volume": 50.0,
        }
        for i in range(30)
    ]


def test_multi_symbol_interleaving_maintains_temporal_order() -> None:
    runtime = _live_runtime(_interleave_data(), symbols=["BANKNIFTY", "FINNIFTY"])
    runtime.start()
    events = runtime.run_once(max_ticks=30)

    timestamps = []
    for event in events:
        if hasattr(event, "__dict__"):
            value = getattr(event, "timestamp", None)
            if isinstance(value, (int, float)):
                timestamps.append(value)
    assert timestamps
    assert all(earlier <= later for earlier, later in zip(timestamps, timestamps[1:]))
