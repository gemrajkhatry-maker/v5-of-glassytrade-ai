"""End-to-end live wiring: MarketFeed → bus → OrderflowService → /ws/stream.

Mirrors ``TradingSession.live()``'s assembly (ThreadSafeReactiveBus +
ExecutionEngine(BrokerFillSource) + compose(mode="live") + MarketFeed), but
with a fake broker whose WS handlers can be fired manually to simulate the
Dhan/Upstox receive threads. Proves the standard-interface live path feeds
the attached OrderflowService and streams computed state over the gameloop —
the production flow, no credentials required.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from tradex_domain import BrokerId
from tradex_domain.instruments import Equity
from tradex_domain.market import Depth, Quote
from tradex_domain.value_objects import Price, Quantity

from tradex_trading.execution.engine import ExecutionEngine
from tradex_trading.execution.fill_sources import BrokerFillSource
from tradex_trading.interface.fastapi_app import create_app
from tradex_trading.reactive.thread_safe_bus import ThreadSafeReactiveBus
from tradex_trading.runtime.compose import compose
from tradex_trading.runtime.market_feed import MarketFeed
from tradex_trading.sdk.session import TradingSession

INSTRUMENT = Equity.of("NSE", "RELIANCE")
KEY = "NSE:RELIANCE"
T0 = datetime(2026, 8, 8, 9, 15, 0, tzinfo=UTC)


class _FakeLiveBroker:
    """Minimal live-broker surface: stream subscribe handlers + manual emit.

    ``emit_quote``/``emit_depth`` stand in for the Dhan/Upstox WS receive
    threads invoking the registered handler for a streamed tick.
    """

    def __init__(self) -> None:
        self._quote_handlers: list[Any] = []
        self._depth_handlers: list[Any] = []

    def subscribe_quotes(self, instruments, handler) -> str:
        self._quote_handlers.append(handler)
        return f"q-{len(self._quote_handlers)}"

    def subscribe_depth(self, instruments, handler) -> str:
        self._depth_handlers.append(handler)
        return f"d-{len(self._depth_handlers)}"

    def unsubscribe(self, subscription) -> None:
        pass

    def close(self) -> None:
        pass

    def emit_quote(self, quote: Quote) -> None:
        for handler in tuple(self._quote_handlers):
            handler(quote)

    def emit_depth(self, depth: Depth) -> None:
        for handler in tuple(self._depth_handlers):
            handler(depth)


def _make_live_session() -> tuple[TradingSession, _FakeLiveBroker]:
    """Assemble a live-mode session exactly like ``TradingSession.live()``."""
    broker = _FakeLiveBroker()
    bus = ThreadSafeReactiveBus()
    engine = ExecutionEngine(bus=bus, fill_source=BrokerFillSource(broker=broker))
    session = compose(
        broker=broker,  # type: ignore[arg-type] — duck-typed live broker
        bus=bus,
        engine=engine,
        broker_id=BrokerId.DHAN,
        mode="live",
    )
    session._market_feed = MarketFeed(broker=broker, bus=bus)
    return session, broker


def _quote(ltp: float, ts: datetime) -> Quote:
    return Quote(
        instrument=INSTRUMENT,
        ltp=Price(value=Decimal(str(ltp))),
        bid=Price(value=Decimal(str(ltp - 0.05))),
        ask=Price(value=Decimal(str(ltp))),
        volume=Quantity(value=Decimal("100")),
        timestamp=ts,
    )


def _depth() -> Depth:
    return Depth(
        instrument=INSTRUMENT,
        bids=((Price(Decimal("99")), Quantity(Decimal("100"))),),
        asks=((Price(Decimal("101")), Quantity(Decimal("50"))),),
        timestamp=T0,
    )


def test_live_quote_feed_populates_orderflow_footprint() -> None:
    """A live MarketFeed quote tick reaches the attached OrderflowService."""
    session, broker = _make_live_session()
    try:
        session.start_market_feed([INSTRUMENT])
        broker.emit_quote(_quote(100.5, T0))

        fp = session.orderflow.footprint(KEY)
        assert fp != {}
        assert fp[100.5].ask_volume == 100.0  # LTP at ask → buyer aggressive
    finally:
        session.stop()


def test_live_depth_feed_populates_orderbook_state() -> None:
    """A live MarketFeed depth tick reaches the attached OrderflowService."""
    session, broker = _make_live_session()
    try:
        session.market_feed.subscribe([INSTRUMENT], depth="20")
        broker.emit_depth(_depth())

        book = session.orderflow.orderbook(KEY)
        assert book is not None
        assert book.best_bid == 99.0
        assert book.best_ask == 101.0
    finally:
        session.stop()


def test_live_feed_streams_orderflow_over_ws_gameloop() -> None:
    """Full production flow: broker tick → MarketFeed → bus → OrderflowService
    → OrderflowUpdate → /ws/stream orderflow message."""
    session, broker = _make_live_session()
    try:
        # Quotes + depth, mirroring a live client's depth-enabled subscription.
        session.market_feed.start([INSTRUMENT], depth="20")
        app = create_app(session=session)
        client = TestClient(app)
        with client.websocket_connect("/ws/stream") as ws:
            ws.send_text(json.dumps({
                "type": "subscribe_orderflow",
                "instruments": [KEY],
            }))
            assert ws.receive_json()["type"] == "subscribed_orderflow"
            assert ws.receive_json()["type"] == "orderflow"  # snapshot

            # A live depth tick streams orderbook state immediately.
            broker.emit_depth(_depth())
            msg = ws.receive_json()
            assert msg["type"] == "orderflow"
            assert msg["kind"] == "depth"
            assert msg["orderbook"]["best_bid"] == 99.0

            # A live quote crossing the M1 boundary closes a bar → footprint.
            broker.emit_quote(_quote(100.5, T0))
            broker.emit_quote(_quote(100.6, T0 + timedelta(minutes=1)))
            msg = ws.receive_json()
            assert msg["type"] == "orderflow"
            assert msg["kind"] == "bar"
            assert msg["footprint"] != {}
            assert msg["delta"]["vertical_delta"] == 100.0
    finally:
        session.stop()
