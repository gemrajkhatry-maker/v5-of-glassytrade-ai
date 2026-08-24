"""Orderflow streaming over the /ws/stream gameloop.

The session's shared ``OrderflowService`` publishes ``OrderflowUpdate`` events
on the reactive bus (on bar close and depth update). The WebSocket gameloop
subscribes to those events and, for instruments a client opted into via
``subscribe_orderflow``, forwards a serialized snapshot of the computed
orderflow state (footprint/delta/volume-profile/orderbook/signals).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from tradex_domain.instruments import Equity
from tradex_domain.market import Depth, Quote
from tradex_domain.value_objects import Price, Quantity

from tradex_trading.interface.fastapi_app import create_app
from tradex_trading.sdk.session import TradingSession

INSTRUMENT = Equity.of("NSE", "RELIANCE")
KEY = "NSE:RELIANCE"
T0 = datetime(2026, 8, 8, 9, 15, 0, tzinfo=UTC)


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


def _make_client() -> tuple[TestClient, TradingSession]:
    session = TradingSession.paper()
    app = create_app(session=session)
    return TestClient(app), session


def test_subscribe_orderflow_acks_and_pushes_snapshot() -> None:
    client, session = _make_client()
    try:
        with client.websocket_connect("/ws/stream") as ws:
            ws.send_text(json.dumps({
                "type": "subscribe_orderflow",
                "instruments": [KEY],
            }))
            ack = ws.receive_json()
            assert ack["type"] == "subscribed_orderflow"
            assert ack["instruments"] == [KEY]

            # An immediate snapshot is pushed so a fresh dashboard doesn't wait
            # for the next bar/depth update.
            snap = ws.receive_json()
            assert snap["type"] == "orderflow"
            assert snap["kind"] == "snapshot"
            assert snap["instrument"] == KEY
            assert snap["footprint"] == {}
            assert snap["delta"] is None
            assert snap["orderbook"] is None
    finally:
        session.stop()


def test_depth_update_streams_orderbook_state() -> None:
    client, session = _make_client()
    try:
        with client.websocket_connect("/ws/stream") as ws:
            ws.send_text(json.dumps({
                "type": "subscribe_orderflow",
                "instruments": [KEY],
            }))
            assert ws.receive_json()["type"] == "subscribed_orderflow"
            assert ws.receive_json()["type"] == "orderflow"  # snapshot

            session.bus.publish(_depth())

            msg = ws.receive_json()
            assert msg["type"] == "orderflow"
            assert msg["kind"] == "depth"
            assert msg["instrument"] == KEY
            assert msg["orderbook"]["best_bid"] == 99.0
            assert msg["orderbook"]["best_ask"] == 101.0
    finally:
        session.stop()


def test_bar_close_streams_footprint_and_delta() -> None:
    client, session = _make_client()
    try:
        with client.websocket_connect("/ws/stream") as ws:
            ws.send_text(json.dumps({
                "type": "subscribe_orderflow",
                "instruments": [KEY],
            }))
            assert ws.receive_json()["type"] == "subscribed_orderflow"
            assert ws.receive_json()["type"] == "orderflow"  # snapshot

            # Two buyer-aggressive quotes across an M1 boundary: the second
            # closes the first bar, which emits the "bar" orderflow update.
            session.bus.publish(_quote(100.5, T0))
            session.bus.publish(_quote(100.6, T0 + timedelta(minutes=1)))

            msg = ws.receive_json()
            assert msg["type"] == "orderflow"
            assert msg["kind"] == "bar"
            assert msg["instrument"] == KEY
            assert msg["footprint"] != {}
            assert msg["delta"]["vertical_delta"] == 100.0
            assert msg["delta"]["cumulative_delta"] == 100.0
    finally:
        session.stop()


def test_unsubscribe_orderflow_stops_streaming() -> None:
    client, session = _make_client()
    try:
        with client.websocket_connect("/ws/stream") as ws:
            ws.send_text(json.dumps({
                "type": "subscribe_orderflow",
                "instruments": [KEY],
            }))
            assert ws.receive_json()["type"] == "subscribed_orderflow"
            assert ws.receive_json()["type"] == "orderflow"  # snapshot

            ws.send_text(json.dumps({
                "type": "unsubscribe_orderflow",
                "instruments": [KEY],
            }))
            ack = ws.receive_json()
            assert ack["type"] == "unsubscribed_orderflow"
            assert ack["instruments"] == [KEY]

            # After unsubscribe, depth no longer produces an orderflow message.
            session.bus.publish(_depth())
            # No orderflow message should arrive — verify the socket is still
            # open and responsive via a stats round-trip instead.
            ws.send_text(json.dumps({"type": "stats"}))
            msg = ws.receive_json()
            assert msg["type"] == "stats"
    finally:
        session.stop()
