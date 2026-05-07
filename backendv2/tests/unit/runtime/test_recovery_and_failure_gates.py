"""Failure-injection tests for bounded degradation in runtime execution."""

from app.runtime.feeds import LiveFeed
from app.runtime.orchestrator.session import SessionRuntime
from app.runtime.pipeline import events
from app.runtime.pipeline.events import FillEvent, OrderStatusEvent, PositionEvent, Signal, Tick
from app.runtime.pipeline.execution import ExecutionPipeline


class _FailingBroker:
    async def place_order(self, symbol: str, side: str, quantity: float, price: float):
        raise RuntimeError(f"order rejected for {symbol}:{side}")


def _make_data() -> list[dict]:
    return [
        {
            "symbol": "BANKNIFTY",
            "timestamp": float(i * 1_000_000_000),
            "price": 45000.0 + i * 0.5,
            "volume": 100.0,
            "bid": 44999.0 + i * 0.5,
            "ask": 45001.0 + i * 0.5,
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
            bid_volume=float(row["bid_volume"]),
            ask_volume=float(row["ask_volume"]),
        )
        for row in rows
    ]


def _strategy_signal_from_feature(feature: events.FeatureVector) -> Signal:
    return Signal(
        symbol=feature.symbol,
        timestamp=feature.timestamp,
        type="LONG",
        entry=float(feature.vwap),
        sl=float(feature.vwap * 0.985),
        tp=float(feature.vwap * 1.03),
        rr=2.0,
        confidence=0.9,
        reason="broker failure injection",
        source="strategy",
    )


def test_broker_failure_downgrades_to_rejected_without_fill() -> None:
    feed = LiveFeed(symbols=["BANKNIFTY"], tick_source=_to_ticks(_make_data()), strict_symbol_mode=True)
    runtime = SessionRuntime(feed=feed, symbols=["BANKNIFTY"])
    runtime._execution._broker = _FailingBroker()

    runtime.register_strategy(
        symbol="BANKNIFTY",
        strategy_id="failure_guard",
        handler=_strategy_signal_from_feature,
        priority=1,
    )
    runtime.start()
    events_out = runtime.run_once(max_ticks=130)

    opened = [
        event
        for event in events_out
        if isinstance(event, PositionEvent) and event.event_type == "OPENED"
    ]
    assert opened, "strategy path should still emit open events"

    open_position_id = opened[0].position_id
    rejected = [
        event
        for event in events_out
        if isinstance(event, OrderStatusEvent) and event.order_id == open_position_id
    ]
    assert rejected and rejected[0].status == "REJECTED"

    fills = [
        event
        for event in events_out
        if isinstance(event, FillEvent) and event.order_id == open_position_id
    ]
    assert fills == []

    closed = [
        event
        for event in events_out
        if isinstance(event, PositionEvent)
        and event.event_type == "CLOSED"
        and event.position_id == open_position_id
    ]
    assert closed == []

    runtime_portfolio = runtime._position.get_portfolio("BANKNIFTY")
    assert not runtime_portfolio.has_open_positions()

    risk_snapshot = runtime._risk.snapshot()
    assert risk_snapshot["BANKNIFTY"]["portfolio"]["open_positions"] == []


def test_unbound_execution_rejects_instead_of_synthetic_fill() -> None:
    position_event = PositionEvent(
        symbol="BANKNIFTY",
        timestamp=1_000_000_000,
        event_type="OPENED",
        position_id="pos-1",
        entry_price=45000.0,
        size=1.0,
        side="LONG",
    )
    statuses = ExecutionPipeline().process(position_event)
    assert len(statuses) == 1
    assert statuses[0].status == "REJECTED"
    assert statuses[0].filled_quantity == 0.0
    assert "not bound" in statuses[0].reject_reason
