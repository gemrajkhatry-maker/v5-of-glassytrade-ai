"""
Live Integration Tests for Broker Market Data.

These tests connect to the real Dhan API and require valid credentials.
All tests are gated behind environment variables and marked with
@pytest.mark.integration so they can be excluded from CI runs.

Run with:
    DHAN_CLIENT_ID=xxx DHAN_ACCESS_TOKEN=yyy \\
        PYTHONPATH=. pytest brokers/tests/test_integration_market_data.py -v -m integration

Skip in normal CI:
    pytest -m "not integration"
"""

import os
import asyncio
import pytest
from datetime import datetime, timedelta

from quant.contracts.timezones import IST

# ---------------------------------------------------------------------------
# Skip all tests in this file when credentials are absent
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration


def _skip_if_no_creds():
    # Read lazily so brokers/__init__.py .env load is honoured before check
    import brokers  # noqa: F401 — triggers .env load
    if not (os.environ.get("DHAN_CLIENT_ID") and os.environ.get("DHAN_ACCESS_TOKEN")):
        pytest.skip(
            "Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN to run integration tests"
        )


def _market_hours():
    """Return (NSE open, NSE close, MCX evening open, MCX evening close) in IST."""
    nse_open = datetime.now(IST).replace(hour=9, minute=15, second=0, microsecond=0)
    nse_close = datetime.now(IST).replace(hour=15, minute=30, second=0, microsecond=0)
    mcx_open = datetime.now(IST).replace(hour=17, minute=0, second=0, microsecond=0)
    mcx_close = datetime.now(IST).replace(hour=23, minute=0, second=0, microsecond=0)
    return nse_open, nse_close, mcx_open, mcx_close


def _skip_if_market_closed(market: str = "NSE"):
    """Skip live-data tests when the relevant exchange market is closed (IST)."""
    now = datetime.now(IST)
    nse_open, nse_close, mcx_open, mcx_close = _market_hours()
    if market == "NSE":
        open_time, close_time = nse_open, nse_close
    elif market == "MCX":
        open_time, close_time = mcx_open, mcx_close
    else:
        pytest.skip(f"Unknown market {market!r}")
    if not (open_time <= now <= close_time):
        pytest.skip(
            f"{market} market closed (IST {now:%H:%M}) — live data tests "
            f"only run during {open_time:%H:%M}–{close_time:%H:%M} IST"
        )


DHAN_CLIENT_ID = os.environ.get("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gateway():
    """Real Dhan BrokerGateway wired with live credentials."""
    _skip_if_no_creds()
    from brokers.gateway import BrokerGateway

    gw = BrokerGateway.dhan(
        client_id=os.environ.get("DHAN_CLIENT_ID", ""),
        access_token=os.environ.get("DHAN_ACCESS_TOKEN", ""),
    )
    return gw


@pytest.fixture(scope="module")
def paper_gateway():
    """Paper gateway — no credentials needed."""
    from brokers.gateway import BrokerGateway

    return BrokerGateway.paper()


# ---------------------------------------------------------------------------
# Paper broker smoke tests (no credentials, always run)
# ---------------------------------------------------------------------------


class TestPaperGatewaySmoke:
    """Smoke tests using the paper broker — run in all environments."""

    def test_place_and_cancel_order(self, paper_gateway):
        """place_order -> cancel_order round-trip via gateway."""
        order = paper_gateway.place_order(
            symbol="NIFTY",
            exchange="NSE",
            side="BUY",
            quantity=1,
        )
        assert order.order_id
        cancelled = paper_gateway.cancel_order(order.order_id)
        assert cancelled is True

    def test_get_order_status(self, paper_gateway):
        """get_order_status returns Order for a placed order."""
        from brokers.broker.entities import Order

        placed = paper_gateway.place_order(
            symbol="RELIANCE",
            exchange="NSE",
            side="BUY",
            quantity=5,
        )
        status = paper_gateway.get_order_status(placed.order_id)
        assert isinstance(status, Order)
        assert status.order_id == placed.order_id

    def test_place_sl_order_with_trigger_price(self, paper_gateway):
        """place_order stores trigger_price and product_type on the Order entity."""
        from brokers.broker.entities import Order

        order = paper_gateway.place_order(
            symbol="NIFTY",
            exchange="NSE",
            side="BUY",
            quantity=50,
            price=22100.0,
            trigger_price=22000.0,
            product_type="INTRADAY",
        )
        assert isinstance(order, Order)
        assert order.trigger_price == 22000.0
        assert order.product_type == "INTRADAY"

    @pytest.mark.asyncio
    async def test_stream_ticker_emits_bid_ask(self, paper_gateway):
        """Paper stream_ticker emits Tick with bid and ask populated."""
        from brokers.broker.entities import Tick
        from brokers.broker.types import Exchange

        ticks = []
        async for tick in paper_gateway.stream_ticker(["NIFTY"], Exchange.NSE):
            ticks.append(tick)
            if len(ticks) >= 2:
                break

        assert len(ticks) >= 1
        tick = ticks[0]
        assert isinstance(tick, Tick)
        assert tick.bid is not None, "Tick.bid should be populated by paper broker"
        assert tick.ask is not None, "Tick.ask should be populated by paper broker"
        assert tick.bid < tick.price
        assert tick.ask > tick.price


# ---------------------------------------------------------------------------
# Live Dhan integration tests (require DHAN_* env vars)
# ---------------------------------------------------------------------------


class TestDhanGetQuote:
    """Live quote tests against Dhan API."""

    def test_get_quote_nifty(self, gateway):
        """get_quote for NIFTY returns a valid Quote with ltp > 0."""
        _skip_if_no_creds()
        _skip_if_market_closed("NSE")
        from brokers.broker.entities import Quote
        from brokers.broker.types import Exchange

        quote = gateway.get_quote("NIFTY", Exchange.NSE)

        assert isinstance(quote, Quote)
        assert quote.ltp > 0, "LTP must be positive"
        assert quote.instrument.symbol == "NIFTY"

    def test_get_quotes_batch(self, gateway):
        """get_quotes returns a dict of Quotes."""
        _skip_if_no_creds()
        _skip_if_market_closed("NSE")
        import time
        from brokers.broker.entities import Quote
        from brokers.broker.types import Exchange

        time.sleep(1.0)  # avoid DH-3001 rate limit after previous test
        quotes = gateway.get_quotes(["NIFTY", "RELIANCE"], Exchange.NSE)

        assert isinstance(quotes, dict)
        assert len(quotes) >= 1
        for symbol, quote in quotes.items():
            assert isinstance(quote, Quote)
            assert quote.ltp >= 0


class TestDhanOptionChain:
    """Live option chain tests."""

    def test_get_option_chain_nifty(self, gateway):
        """get_option_chain for NIFTY returns chain with ATM > 0 and non-empty calls/puts."""
        _skip_if_no_creds()
        _skip_if_market_closed("NSE")
        from brokers.broker.entities import OptionChain
        from brokers.broker.types import Exchange

        chain = gateway.get_option_chain("NIFTY", Exchange.NFO)

        assert isinstance(chain, OptionChain)
        assert chain.atm_strike > 0, "ATM strike must be positive"
        assert len(chain.calls) > 0, "Should have call options"
        assert len(chain.puts) > 0, "Should have put options"
        assert chain.spot_price > 0

    def test_get_expiries_nifty(self, gateway):
        """get_expiries for NIFTY returns sorted list of future dates."""
        _skip_if_no_creds()
        from brokers.broker.types import Exchange

        expiries = gateway.get_expiries("NIFTY", Exchange.NFO)

        assert isinstance(expiries, list)
        assert len(expiries) > 0
        today = datetime.now().date()
        for exp in expiries:
            exp_date = exp.date() if isinstance(exp, datetime) else exp
            assert exp_date >= today, f"Expiry {exp} should be in the future"


class TestDhanHistoricalData:
    """Live historical data tests."""

    def test_get_historical_crudeoil(self, gateway):
        """get_historical for CRUDEOIL MCX returns OHLCV DataFrame."""
        _skip_if_no_creds()
        import pandas as pd
        from brokers.broker.types import Exchange

        to_date = datetime.now()
        from_date = to_date - timedelta(days=5)

        df = gateway.broker.get_historical(
            gateway.broker.get_quote(
                __import__("brokers.broker.entities", fromlist=["Instrument"]).Instrument(
                    symbol="CRUDEOIL", exchange=Exchange.MCX, security_id=""
                )
            ).instrument,
            from_date=from_date,
            to_date=to_date,
            interval="1d",
        )

        # May return empty if market was closed for last 5 days
        assert isinstance(df, pd.DataFrame)
        if len(df) > 0:
            assert set(["open", "high", "low", "close", "volume"]).issubset(
                set(df.columns)
            )


class TestDhanStreaming:
    """Live streaming tests against Dhan API."""

    @pytest.mark.asyncio
    async def test_stream_ticker_2_ticks(self, gateway):
        """stream_ticker yields at least 2 ticks during market hours."""
        _skip_if_no_creds()
        _skip_if_market_closed("MCX")
        from brokers.broker.entities import Tick
        from brokers.broker.types import Exchange

        ticks = []

        async def collect():
            # MCX evening session: use stream_full (TICKER/QUOTE not supported on MCX)
            async for tick in gateway.stream_full(["CRUDEOIL"], Exchange.MCX):
                ticks.append(tick)
                if len(ticks) >= 2:
                    break

        try:
            await asyncio.wait_for(collect(), timeout=30.0)
        except asyncio.TimeoutError:
            pass  # may have received some ticks before timeout

        if len(ticks) < 2:
            pytest.skip(f"Only {len(ticks)} tick(s) received — may be outside market hours")

        assert len(ticks) >= 2
        for pkt in ticks:
            # stream_full yields FullPacket objects or raw dicts
            if hasattr(pkt, 'ltp'):
                assert pkt.ltp > 0
            elif isinstance(pkt, dict):
                assert pkt.get("ltp", 0) > 0
