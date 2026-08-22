"""OrderflowService boot wiring — the live session feeds it via the bus.

``runtime.compose`` forces ``session.orderflow`` so every boot path
(``TradingSession.paper()`` / ``.live()`` / ``startup.boot``) attaches the
analytics service to the reactive quote/depth bus without needing the HTTP
API to be opened. This test proves the wiring end-to-end: a ``Quote`` published
on the session bus lands in the service's per-instrument footprint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradex_domain import Quote
from tradex_domain.instruments import Equity
from tradex_domain.value_objects import Price, Quantity

from tradex_trading.analytics.orderflow_service import OrderflowService
from tradex_trading.runtime.startup import boot
from tradex_trading.sdk.session import TradingSession

INSTRUMENT = Equity.of("NSE", "RELIANCE")
INSTRUMENT_ID = str(INSTRUMENT.instrument_id)


def _buyer_quote(ltp: float) -> Quote:
    """A buyer-aggressive quote (LTP at ask) with volume → footprint ask volume."""
    return Quote(
        instrument=INSTRUMENT,
        ltp=Price(value=Decimal(str(ltp))),
        bid=Price(value=Decimal(str(ltp - 0.05))),
        ask=Price(value=Decimal(str(ltp))),
        volume=Quantity(value=Decimal("100")),
        timestamp=datetime(2026, 8, 8, 9, 15, 0, tzinfo=UTC),
    )


def test_paper_session_attaches_orderflow_service() -> None:
    """compose() forces session.orderflow: it is constructed, attached, and
    returns the same cached instance on every access."""
    session = TradingSession.paper()
    try:
        svc = session.orderflow
        assert isinstance(svc, OrderflowService)
        # cached_property — repeated access is the same instance (no double attach).
        assert session.orderflow is svc
    finally:
        session.stop()


def test_boot_path_attaches_orderflow_service() -> None:
    """startup.boot (paper) routes through compose() and attaches the service
    too — the production boot path, not just the session factories."""
    session = boot()
    try:
        assert isinstance(session.orderflow, OrderflowService)
    finally:
        session.stop()


def test_quote_published_on_bus_populates_orderflow_footprint() -> None:
    """A Quote published on the session bus reaches the attached service and
    accumulates footprint state — the live-path contract in production."""
    session = TradingSession.paper()
    try:
        svc = session.orderflow
        assert svc.footprint(INSTRUMENT_ID) == {}

        session.bus.publish(_buyer_quote(100.0))

        fp = svc.footprint(INSTRUMENT_ID)
        assert fp != {}
        level = next(iter(fp.values()))
        # LTP at ask → aggressor is the buyer → ask (buy) volume attributed.
        assert level.ask_volume == 100.0
    finally:
        session.stop()
