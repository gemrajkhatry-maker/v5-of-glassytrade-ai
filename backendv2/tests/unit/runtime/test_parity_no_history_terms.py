"""Parity and deterministic guards for runtime execution."""

from app.runtime.feeds import LiveFeed
from app.runtime.pipeline.events import Tick
from app.runtime.orchestrator.session import SessionRuntime


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
        for i in range(60)
    ]


def _signature(events: list[object]) -> list[tuple[str, dict]]:
    payloads: list[tuple[str, dict]] = []
    for event in events:
        if hasattr(event, "__dict__"):
            data = dict(getattr(event, "__dict__"))
            data.pop("id", None)
            data.pop("order_id", None)
            data.pop("position_id", None)
            payloads.append((type(event).__name__, data))
        else:
            payloads.append((type(event).__name__, {"value": str(event)}))
    return payloads


def _to_ticks(data: list[dict]) -> list[Tick]:
    return [
        Tick(
            symbol=row["symbol"],
            timestamp=row["timestamp"],
            price=row["price"],
            volume=row["volume"],
            bid=row["bid"],
            ask=row["ask"],
            bid_volume=row["bid_volume"],
            ask_volume=row["ask_volume"],
        )
        for row in data
    ]


def _run_live_runtime_from_ticks(ticks: list[Tick]) -> list[object]:
    feed = LiveFeed(
        symbols=["BANKNIFTY"],
        tick_source=ticks,
        strict_symbol_mode=True,
    )
    runtime = SessionRuntime(feed=feed, symbols=["BANKNIFTY"])
    runtime.start()
    return runtime.run_once(max_ticks=len(ticks))


def test_live_and_live_runtime_events_are_isomorphic() -> None:
    data = _make_data()
    live_baseline = _run_live_runtime_from_ticks(_to_ticks(data))
    live_comparison = _run_live_runtime_from_ticks(_to_ticks(list(data)))

    assert _signature(live_baseline) == _signature(live_comparison)


