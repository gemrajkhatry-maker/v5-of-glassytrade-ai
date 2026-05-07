"""Deterministic parity test for equivalent live tick feeds."""

from app.runtime.feeds import LiveFeed
from app.runtime.orchestrator.session import SessionRuntime
from app.runtime.pipeline.events import Tick


def _make_data():
    return [
        {"symbol": "BANKNIFTY", "timestamp": 0, "price": 45000.0, "volume": 100, "bid": 44999.0, "ask": 45001.0},
        {"symbol": "BANKNIFTY", "timestamp": 1_000_000_000, "price": 45010.0, "volume": 120, "bid": 45009.0, "ask": 45011.0},
        {"symbol": "BANKNIFTY", "timestamp": 2_000_000_000, "price": 45005.0, "volume": 80, "bid": 45004.0, "ask": 45006.0},
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

def test_live_runtime_is_deterministic_for_same_live_feed():
    base_data = _make_data()
    live_a = SessionRuntime(feed=LiveFeed(symbols=["BANKNIFTY"], tick_source=_to_ticks(base_data), strict_symbol_mode=True), symbols=["BANKNIFTY"])
    live_b = SessionRuntime(feed=LiveFeed(symbols=["BANKNIFTY"], tick_source=_to_ticks(list(base_data)), strict_symbol_mode=True), symbols=["BANKNIFTY"])

    live_a.start()
    live_b.start()

    events_a = live_a.run_once(max_ticks=len(base_data))
    events_b = live_b.run_once(max_ticks=len(base_data))

    assert _signature(events_a) == _signature(events_b)
