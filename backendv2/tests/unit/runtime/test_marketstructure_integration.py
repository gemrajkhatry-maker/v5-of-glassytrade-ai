"""Deterministic validation of market-structure context propagation."""

from app.runtime.feeds import LiveFeed
from app.runtime.orchestrator.session import SessionRuntime
from app.runtime.pipeline.events import Tick
from app.runtime.pipeline.events import MarketStructureResult


def _make_data() -> list[dict]:
    return [
        {
            "symbol": "BANKNIFTY",
            "timestamp": float(i * 60_000_000_000),
            "price": 45000.0 + i,
            "volume": 100.0,
            "bid": 44999.5 + i,
            "ask": 45000.5 + i,
        }
        for i in range(16)
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


def test_market_structure_updates_follow_m1_boundary_only():
    runtime = SessionRuntime(
        feed=LiveFeed(symbols=["BANKNIFTY"], tick_source=_to_ticks(_make_data()), strict_symbol_mode=True),
        symbols=["BANKNIFTY"],
    )
    runtime.start()
    events = runtime.run_once(max_ticks=16)

    market_events = [event for event in events if isinstance(event, MarketStructureResult)]
    assert market_events, "Expected market-structure events in runtime output"

    # A deterministic runtime must emit market-structure updates from 1-minute
    # candles only, even when 5m/15m boundaries close on the same tick.
    timestamps = [int(event.timestamp) for event in market_events]
    assert len(timestamps) == 15
    assert all(t2 - t1 == 60_000_000_000 for t1, t2 in zip(timestamps, timestamps[1:])), (
        "Market-structure updates should remain on 1-minute cadence."
    )
    assert timestamps[-1] == 900_000_000_000

