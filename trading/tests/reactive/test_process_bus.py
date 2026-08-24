"""Cross-process reactive bus bridge tests."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tradex_domain import (
    OHLC,
    Candle,
    CandleReceived,
    Depth,
    Equity,
    Price,
    Quantity,
    Quote,
    Timeframe,
)

from tradex_trading.reactive.process_bus import ProcessBusClient, ProcessBusServer
from tradex_trading.reactive.thread_safe_bus import ThreadSafeReactiveBus


def _socket_path(tmp_path) -> str:
    path = tmp_path / "bus.sock"
    if len(str(path).encode()) >= 100:
        pytest.skip("Unix socket path is too long for AF_UNIX")
    return str(path)


def _event() -> CandleReceived:
    instrument = Equity.of("NSE", "RELIANCE")
    candle = Candle(
        instrument=instrument,
        timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(Decimal("100")),
            high=Price(Decimal("101")),
            low=Price(Decimal("99")),
            close=Price(Decimal("100.5")),
        ),
        volume=Quantity(Decimal("10")),
        timestamp=datetime(2026, 8, 23, 9, 15, tzinfo=UTC),
    )
    return CandleReceived(candle=candle)


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "timed out waiting for process bus delivery"


def test_server_broadcasts_local_events_to_client(tmp_path) -> None:
    server_bus = ThreadSafeReactiveBus()
    client_bus = ThreadSafeReactiveBus()
    path = _socket_path(tmp_path)
    server = ProcessBusServer(server_bus, path).start()
    received: list[CandleReceived] = []
    client_bus.of_type(CandleReceived).subscribe(received.append)
    client = ProcessBusClient(client_bus, server.address, authkey=server.authkey).connect()
    try:
        server_bus.publish(_event())
        _wait_for(lambda: len(received) == 1)
        assert received[0].candle.instrument == Equity.of("NSE", "RELIANCE")
        assert received[0].candle.ohlc.close.value == Decimal("100.5")
    finally:
        client.close()
        server.close()


def test_client_event_reaches_server_without_echo(tmp_path) -> None:
    server_bus = ThreadSafeReactiveBus()
    client_bus = ThreadSafeReactiveBus()
    path = _socket_path(tmp_path)
    server = ProcessBusServer(server_bus, path).start()
    client = ProcessBusClient(client_bus, server.address, authkey=server.authkey).connect()
    server_received: list[CandleReceived] = []
    client_received: list[CandleReceived] = []
    server_bus.of_type(CandleReceived).subscribe(server_received.append)
    client_bus.of_type(CandleReceived).subscribe(client_received.append)
    try:
        client_bus.publish(_event())
        _wait_for(lambda: len(server_received) == 1)
        time.sleep(0.05)
        assert len(server_received) == 1
        assert client_received == [_event()]
    finally:
        client.close()
        server.close()


def test_quote_and_depth_reach_client(tmp_path) -> None:
    server_bus = ThreadSafeReactiveBus()
    client_bus = ThreadSafeReactiveBus()
    path = _socket_path(tmp_path)
    server = ProcessBusServer(server_bus, path).start()
    received_depth: list[Depth] = []
    received_quote: list[Quote] = []
    client_bus.of_type(Depth).subscribe(received_depth.append)
    client_bus.of_type(Quote).subscribe(received_quote.append)
    client = ProcessBusClient(client_bus, server.address, authkey=server.authkey).connect()
    instrument = Equity.of("NSE", "RELIANCE")
    depth = Depth(
        instrument=instrument,
        bids=((Price(Decimal("99")), Quantity(Decimal("5"))),),
        asks=((Price(Decimal("101")), Quantity(Decimal("5"))),),
    )
    quote = Quote(instrument=instrument, ltp=Price(Decimal("100")), depth=depth)
    try:
        server_bus.publish(depth)
        server_bus.publish(quote)
        _wait_for(lambda: len(received_depth) == 1 and len(received_quote) == 1)
        assert received_depth[0] == depth
        assert received_quote[0] == quote
    finally:
        client.close()
        server.close()


def test_wrong_authkey_is_rejected(tmp_path) -> None:
    server_bus = ThreadSafeReactiveBus()
    path = _socket_path(tmp_path)
    server = ProcessBusServer(server_bus, path).start()
    try:
        with pytest.raises(ConnectionError):
            ProcessBusClient(
                ThreadSafeReactiveBus(), server.address, authkey=b"wrong-key"
            ).connect()
    finally:
        server.close()


def test_non_domain_messages_are_rejected(tmp_path) -> None:
    server_bus = ThreadSafeReactiveBus()
    path = _socket_path(tmp_path)
    server = ProcessBusServer(server_bus, path).start()
    client = ProcessBusClient(
        ThreadSafeReactiveBus(), server.address, authkey=server.authkey
    ).connect()
    try:
        with pytest.raises(TypeError, match="DomainEvent, Depth, and Quote"):
            client._send_local("not an event")
    finally:
        client.close()
        server.close()
