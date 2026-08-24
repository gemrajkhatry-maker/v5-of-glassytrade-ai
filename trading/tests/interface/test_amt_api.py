"""Tests for the AMT dashboard endpoints (via AMTService)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from tradex_domain import OHLC, Candle, Equity, Price, Quantity, Quote, Timeframe

from tradex_trading.interface.fastapi_app import create_app
from tradex_trading.sdk.services.amt import AMTService

INSTRUMENT = Equity.of("NSE", "RELIANCE")
KEY = "NSE:RELIANCE"
BASE = datetime(2026, 8, 1, 9, 15, tzinfo=UTC)


def _candle(i: int) -> Candle:
    return Candle(
        instrument=INSTRUMENT, timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(Decimal("100")), high=Price(Decimal("101")),
            low=Price(Decimal("99")), close=Price(Decimal("100")),
        ),
        volume=Quantity(Decimal("100")),
        timestamp=BASE + timedelta(minutes=i),
    )


def test_amt_endpoints_empty_when_no_data() -> None:
    app = create_app()
    client = TestClient(app)
    assert client.get(f"/amt/snapshot/{KEY}").status_code == 404
    assert client.get(f"/amt/history/{KEY}").status_code == 200
    assert client.get(f"/amt/history/{KEY}").json() == []
    assert client.get("/amt/scanner").json() == []


def test_amt_snapshot_endpoint_after_feed() -> None:
    app = create_app()
    svc: AMTService = app.state.amt
    for i in range(6):
        svc.on_candle(_candle(i))

    client = TestClient(app)
    snap = client.get(f"/amt/snapshot/{KEY}")
    assert snap.status_code == 200
    body = snap.json()
    assert body["instrument"] == KEY
    assert body["phase"] == "WAITING"
    assert body["vwap"] == "100"

    hist = client.get(f"/amt/history/{KEY}")
    assert hist.status_code == 200
    assert len(hist.json()) == 6


def test_amt_scanner_endpoint_after_feed() -> None:
    app = create_app()
    svc: AMTService = app.state.amt
    # Flat tape for RELIANCE produces no setup -> scanner stays empty.
    for i in range(12):
        svc.on_candle(_candle(i))

    client = TestClient(app)
    assert client.get("/amt/scanner").json() == []


def test_amt_ws_streams_snapshot_updates() -> None:
    app = create_app()
    svc: AMTService = app.state.amt

    client = TestClient(app)
    with client.websocket_connect("/ws/amt") as ws:
        # Initial snapshots (none) then a live update.
        svc.on_candle(_candle(0))
        message = ws.receive_json()
        assert message["instrument"] == KEY
        assert message["phase"] == "WAITING"


def _flow_quote(minute: int, *, ltp: str, bid: str, ask: str, volume: str = "50") -> Quote:
    return Quote(
        instrument=INSTRUMENT,
        ltp=Price(Decimal(ltp)),
        bid=Price(Decimal(bid)),
        ask=Price(Decimal(ask)),
        volume=Quantity(Decimal(volume)),
        timestamp=BASE + timedelta(minutes=minute),
    )


def _triple_a_quotes() -> list[Quote]:
    events = []
    for minute in range(20):
        events.append(_flow_quote(minute, ltp="99.5", bid="99.5", ask="100.5"))
        events.append(_flow_quote(minute, ltp="100.5", bid="99.5", ask="100.5"))
    events.append(_flow_quote(20, ltp="100.3", bid="100.0", ask="100.3", volume="500"))
    events.append(_flow_quote(21, ltp="99.5", bid="99.5", ask="100.5"))
    events.append(_flow_quote(21, ltp="100.5", bid="99.5", ask="100.5"))
    events.append(_flow_quote(22, ltp="101.5", bid="101.0", ask="101.5", volume="100"))
    events.append(_flow_quote(23, ltp="101.0", bid="100.5", ask="101.5"))
    return events


def test_amt_decisions_endpoint_after_triple_a_tape() -> None:
    app = create_app()
    svc: AMTService = app.state.amt
    for quote in _triple_a_quotes():
        svc.on_quote(quote)

    client = TestClient(app)
    body = client.get(f"/amt/decisions/{KEY}").json()
    assert isinstance(body, list)
    assert any(r["approved"] and r["setup"] == "TRIPLE_A" for r in body)
    approved = [r for r in body if r["approved"]][-1]
    assert approved["direction"] == "LONG"
    assert approved["entry"] is not None
    assert approved["failed_gates"] == []


def test_amt_decisions_endpoint_empty_without_data() -> None:
    app = create_app()
    client = TestClient(app)
    assert client.get(f"/amt/decisions/{KEY}").json() == []
