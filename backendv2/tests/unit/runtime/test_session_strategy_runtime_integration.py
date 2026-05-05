"""Session-runtime integration contract for strategy event injection."""

from app.runtime.feeds import LiveFeed
from app.runtime.orchestrator.session import SessionRuntime
from app.runtime.pipeline.events import Tick
from app.runtime.pipeline.events import PositionEvent, Signal


def _make_data() -> list[dict]:
    return [
        {
            "symbol": "BANKNIFTY",
            "timestamp": float(i * 60_000_000_000),
            "price": 45000.0 + (i * 2),
            "volume": 100.0,
            "bid": 44999.0 + (i * 2),
            "ask": 45001.0 + (i * 2),
            "bid_volume": 50.0,
            "ask_volume": 50.0,
        }
        for i in range(8)
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


def _strategy_signal_from_feature(feature) -> Signal:
    return Signal(
        symbol=feature.symbol,
        timestamp=feature.timestamp,
        type="LONG",
        entry=feature.vwap,
        sl=feature.vwap - 20.0,
        tp=feature.vwap + 25.0,
        rr=1.8,
        confidence=0.85,
        reason="test strategy signal",
        source="strategy_rule",
    )


def test_session_executes_registered_strategy_signals():
    runtime = SessionRuntime(
        feed=LiveFeed(symbols=["BANKNIFTY"], tick_source=_to_ticks(_make_data()), strict_symbol_mode=True),
        symbols=["BANKNIFTY"],
    )
    runtime.register_strategy(
        symbol="BANKNIFTY",
        strategy_id="test_strategy",
        handler=_strategy_signal_from_feature,
        priority=10,
    )
    runtime.start()
    events = runtime.run_once(max_ticks=8)

    opened = [event for event in events if isinstance(event, PositionEvent) and event.event_type == "OPENED"]
    closed = [event for event in events if isinstance(event, PositionEvent) and event.event_type == "CLOSED"]

    assert opened, "Expected strategy-driven positions to open"
    assert closed, "Expected strategy-driven position lifecycle to emit closes"
    assert len(opened) == len(closed)


def test_unregistering_strategy_prevents_strategy_signal_flow():
    runtime = SessionRuntime(
        feed=LiveFeed(symbols=["BANKNIFTY"], tick_source=_to_ticks(_make_data()), strict_symbol_mode=True),
        symbols=["BANKNIFTY"],
    )
    runtime.register_strategy(
        symbol="BANKNIFTY",
        strategy_id="temp_strategy",
        handler=_strategy_signal_from_feature,
    )
    runtime.unregister_strategy(symbol="BANKNIFTY", strategy_id="temp_strategy")

    runtime.start()
    events = runtime.run_once(max_ticks=8)
    position_events = [event for event in events if isinstance(event, PositionEvent)]
    assert position_events == []
