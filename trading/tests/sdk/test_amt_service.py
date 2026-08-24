"""AMTService — read-side AMT projection over a reactive bus."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradex_domain import (
    OHLC,
    Candle,
    Equity,
    Fill,
    OrderSide,
    Price,
    Quantity,
    Quote,
    Timeframe,
)
from tradex_domain.execution import OrderId

from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.sdk.services.amt import AMTService, decision_to_dict, snapshot_to_dict
from tradex_trading.strategy.extensions.amt.model import AMTPhase

INSTRUMENT = Equity.of("NSE", "RELIANCE")
BASE = datetime(2026, 8, 1, 9, 15, tzinfo=UTC)


def _candle(i: int, close: str = "100", volume: str = "100") -> Candle:
    price = Decimal(close)
    return Candle(
        instrument=INSTRUMENT, timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(price), high=Price(price + 1),
            low=Price(price - 1), close=Price(price),
        ),
        volume=Quantity(Decimal(volume)),
        timestamp=BASE + timedelta(minutes=i),
    )


def _quote(i: int) -> Quote:
    return Quote(
        instrument=INSTRUMENT,
        ltp=Price(Decimal("100.5")),
        bid=Price(Decimal("100.0")),
        ask=Price(Decimal("100.5")),
        volume=Quantity(Decimal("100")),
        timestamp=BASE + timedelta(minutes=i),
    )


def test_service_projects_snapshots_from_candles() -> None:
    bus = ReactiveBus()
    service = AMTService()
    service.attach(bus)
    for i in range(6):
        bus.publish(_candle(i))

    snapshot = service.snapshot("NSE:RELIANCE")
    assert snapshot is not None
    assert snapshot.instrument == INSTRUMENT
    assert snapshot.phase is AMTPhase.WAITING
    assert snapshot.poc is not None
    assert len(service.history("NSE:RELIANCE")) == 6
    assert service.instruments() == ["NSE:RELIANCE"]
    service.dispose()


def test_service_projects_from_quotes_via_orderflow_builder() -> None:
    bus = ReactiveBus()
    service = AMTService()
    service.attach(bus)
    bus.publish(_quote(0))
    bus.publish(_quote(1))

    snapshot = service.snapshot("NSE:RELIANCE")
    assert snapshot is not None
    assert snapshot.delta == Decimal("100")  # buyer-aggressive print at ask
    service.dispose()


def test_service_snapshot_dto_is_json_safe() -> None:
    service = AMTService()
    service.on_candle(_candle(0))
    dto = snapshot_to_dict(service.snapshot("NSE:RELIANCE"))

    assert dto["instrument"] == "NSE:RELIANCE"
    assert dto["phase"] == "WAITING"
    assert dto["vwap"] == "100"
    assert dto["lvn_levels"] == []
    assert all(isinstance(v, (str, int, float, bool, list, type(None))) for v in dto.values())


def test_service_subscribe_receives_updates_and_disposes() -> None:
    bus = ReactiveBus()
    service = AMTService()
    service.attach(bus)
    received: list = []
    dispose = service.subscribe(received.append)

    bus.publish(_candle(0))
    assert len(received) == 1
    dispose()
    bus.publish(_candle(1))
    assert len(received) == 1
    service.dispose()


def test_service_scan_ranks_setups() -> None:
    service = AMTService()
    # Flat tape -> no setup (excluded).
    for i in range(12):
        service.on_candle(_candle(i))
    results = service.scan()

    assert results == []  # flat tape has no setup
    service.dispose()


def test_attach_is_idempotency_guarded() -> None:
    service = AMTService()
    service.attach(ReactiveBus())
    try:
        service.attach(ReactiveBus())
        raise AssertionError("second attach must raise")
    except RuntimeError:
        pass
    service.dispose()


# --- decision trace ----------------------------------------------------------


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
    """Quote tape that closes a BUY Triple-A decision (mirrors the E2E tape)."""
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


def test_service_records_decision_trace_from_quotes() -> None:
    service = AMTService()
    for quote in _triple_a_quotes():
        service.on_quote(quote)

    records = service.decisions("NSE:RELIANCE")
    assert len(records) >= 1
    approved = [(ts, d) for ts, d in records if d.approved]
    assert approved, "expected at least one approved decision on the Triple-A tape"
    ts, decision = approved[-1]
    assert decision.setup == "TRIPLE_A"
    assert decision.direction == "LONG"
    assert decision.entry is not None
    assert decision.stop_loss < decision.entry < decision.take_profit
    service.dispose()


def test_service_decision_dto_is_json_safe() -> None:
    service = AMTService()
    for quote in _triple_a_quotes():
        service.on_quote(quote)
    records = service.decisions("NSE:RELIANCE")
    ts, decision = next((t, d) for t, d in records if d.approved)

    dto = decision_to_dict(decision, timestamp=ts)
    assert dto["setup"] == "TRIPLE_A"
    assert dto["direction"] == "LONG"
    assert dto["approved"] is True
    assert dto["entry"] is not None
    assert dto["failed_gates"] == []
    assert all(
        isinstance(v, (str, int, float, bool, list, type(None)))
        for v in dto.values()
    )
    service.dispose()


def _high_aggression_quotes(base: int) -> list[Quote]:
    """Fresh absorption -> breakout tape whose breakout bar carries 5x volume."""
    events = []
    for minute in range(20):
        events.append(_flow_quote(base + minute, ltp="99.5", bid="99.5", ask="100.5"))
        events.append(_flow_quote(base + minute, ltp="100.5", bid="99.5", ask="100.5"))
    events.append(_flow_quote(base + 20, ltp="100.3", bid="100.0", ask="100.3", volume="500"))
    events.append(_flow_quote(base + 21, ltp="99.5", bid="99.5", ask="100.5"))
    events.append(_flow_quote(base + 21, ltp="100.5", bid="99.5", ask="100.5"))
    events.append(_flow_quote(base + 22, ltp="101.5", bid="101.0", ask="101.5", volume="500"))
    events.append(_flow_quote(base + 23, ltp="101.0", bid="100.5", ask="101.5"))
    return events


def test_service_decision_trace_sees_pyramid_gate_via_fills() -> None:
    """A same-direction open position plus high aggression yields PYRAMID."""
    service = AMTService()
    bus = ReactiveBus()
    service.attach(bus)
    for quote in _triple_a_quotes():
        bus.publish(quote)
    # Open a LONG position (as the fill source would publish).
    bus.publish(Fill(
        order_id=OrderId("oid-pyramid"),
        instrument=INSTRUMENT,
        side=OrderSide.BUY,
        quantity=Quantity(Decimal("1")),
        price=Price(Decimal("100")),
    ))
    # A fresh absorption -> breakout sequence with a 5x-volume breakout bar
    # while the LONG position is open -> PYRAMID scale-in.
    for quote in _high_aggression_quotes(base=30):
        bus.publish(quote)

    setups = [d.setup for _, d in service.decisions("NSE:RELIANCE")]
    assert "PYRAMID" in setups
    service.dispose()


def test_service_decision_listeners_receive_records() -> None:
    service = AMTService()
    received: list = []
    dispose = service.subscribe_decisions(lambda ts, d: received.append((ts, d)))

    for quote in _triple_a_quotes():
        service.on_quote(quote)
    assert len(received) >= 1
    dispose()
    service.dispose()
