"""Unit tests for the rewritten DhanMarketDataAdapter (brokers/ library integration).

All tests mock DhanBroker so no live credentials are needed.
"""
from __future__ import annotations

import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
import pytest

# Ensure project root is on path so `from brokers.broker...` resolves
_project_root = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import pandas as pd

from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter, _delta_proxy


IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter(exchange="NSE"):
    adapter = DhanMarketDataAdapter(
        symbols=["NIFTY", "BANKNIFTY"],
        exchange=exchange,
        client_id="test_client",
        access_token="test_token",
    )
    return adapter


def _make_mock_broker():
    broker = MagicMock()
    type(broker).is_initialized = PropertyMock(return_value=True)
    type(broker).is_closed = PropertyMock(return_value=False)
    return broker


# ---------------------------------------------------------------------------
# _delta_proxy
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _make_instrument exchange routing (D-EXCH-07 sibling: BSE/BFO must not fall
# through the old binary MCX/NFO branch)
# ---------------------------------------------------------------------------

def test_make_instrument_sensex_option_routes_to_bfo():
    from brokers.broker.types import Exchange

    adapter = _make_adapter()
    instrument = adapter._make_instrument("SENSEX 17 AUG 82000 CALL")
    assert instrument.exchange == Exchange.BFO


def test_make_instrument_sensex_future_routes_to_bfo():
    """Futures branch had its own separate binary MCX/NFO check — must also
    resolve SENSEX/BANKEX futures to BFO, not NFO."""
    from brokers.broker.types import Exchange

    adapter = _make_adapter()
    instrument = adapter._make_instrument("SENSEX AUG FUT")
    assert instrument.exchange == Exchange.BFO


def test_make_instrument_nifty_future_still_routes_to_nfo():
    from brokers.broker.types import Exchange

    adapter = _make_adapter()
    instrument = adapter._make_instrument("NIFTY AUG FUT")
    assert instrument.exchange == Exchange.NFO


def test_make_instrument_crudeoil_future_still_routes_to_mcx():
    from brokers.broker.types import Exchange

    adapter = _make_adapter()
    instrument = adapter._make_instrument("CRUDEOIL AUG FUT")
    assert instrument.exchange == Exchange.MCX


def test_delta_proxy_bullish():
    d = _delta_proxy(100, 110, 90, 110, 1000)
    assert d > 0  # close at high → positive delta

def test_delta_proxy_bearish():
    d = _delta_proxy(100, 110, 90, 90, 1000)
    assert d < 0  # close at low → negative delta

def test_delta_proxy_zero_spread():
    assert _delta_proxy(100, 100, 100, 100, 500) == 0.0

def test_delta_proxy_zero_volume():
    assert _delta_proxy(100, 110, 90, 105, 0) == 0.0


# ---------------------------------------------------------------------------
# get_broker — lazy init and caching
# ---------------------------------------------------------------------------

def test_get_broker_creates_once():
    adapter = _make_adapter()
    mock_broker = _make_mock_broker()

    with patch("brokers.broker.dhan.application.broker.DhanBroker.create", return_value=mock_broker):
        # Import here to patch correctly
        from brokers.broker.dhan.application.broker import DhanBroker
        with patch.object(DhanBroker, "create", return_value=mock_broker) as mock_create:
            adapter._broker = None  # reset
            b1 = adapter.get_broker()
            b2 = adapter.get_broker()

    assert b1 is b2  # same instance returned (cached)


# ---------------------------------------------------------------------------
# fetch_history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_history_returns_ohlc_list():
    adapter = _make_adapter()
    mock_broker = _make_mock_broker()

    # Build a fake DataFrame
    idx = [datetime(2026, 2, 20, 10, tzinfo=IST), datetime(2026, 2, 20, 10, 5, tzinfo=IST)]
    df = pd.DataFrame({
        "open":   [100.0, 102.0],
        "high":   [105.0, 107.0],
        "low":    [98.0,  101.0],
        "close":  [103.0, 106.0],
        "volume": [1000,  1200],
    }, index=idx)
    mock_broker.get_historical.return_value = df

    adapter._broker = mock_broker
    with patch.object(adapter, "_ensure_initialized", new=AsyncMock()):
        result = await adapter.fetch_history("NIFTY", interval="5m", limit=500)

    assert len(result) == 2
    assert result[0].open == 100.0
    assert result[0].high == 105.0
    assert result[0].close == 103.0
    assert result[0].volume == 1000.0


@pytest.mark.asyncio
async def test_fetch_history_empty_df_returns_empty_list():
    adapter = _make_adapter()
    mock_broker = _make_mock_broker()
    mock_broker.get_historical.return_value = pd.DataFrame()

    adapter._broker = mock_broker
    with patch.object(adapter, "_ensure_initialized", new=AsyncMock()):
        result = await adapter.fetch_history("NIFTY", interval="5m")

    assert result == []


@pytest.mark.asyncio
async def test_fetch_history_exception_returns_empty_list():
    adapter = _make_adapter()
    mock_broker = _make_mock_broker()
    mock_broker.get_historical.side_effect = RuntimeError("API error")

    adapter._broker = mock_broker
    with patch.object(adapter, "_ensure_initialized", new=AsyncMock()):
        result = await adapter.fetch_history("NIFTY", interval="5m")

    assert result == []


# ---------------------------------------------------------------------------
# fetch_order_book
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_order_book_builds_from_depth():
    from shared.entities.models import Quote, DepthLevel

    adapter = _make_adapter()
    mock_broker = _make_mock_broker()

    quote = MagicMock(spec=Quote)
    quote.bid_depth = [DepthLevel(price=100.0, quantity=50)]
    quote.ask_depth = [DepthLevel(price=101.0, quantity=30)]
    mock_broker.get_quote.return_value = quote

    adapter._broker = mock_broker
    with patch.object(adapter, "_ensure_initialized", new=AsyncMock()):
        ob = await adapter.fetch_order_book("NIFTY")

    assert ob is not None
    assert ob.bids[0].price == 100.0
    assert ob.asks[0].price == 101.0


@pytest.mark.asyncio
async def test_fetch_order_book_empty_depth_returns_none():
    adapter = _make_adapter()
    mock_broker = _make_mock_broker()

    quote = MagicMock()
    quote.bid_depth = []
    quote.ask_depth = []
    mock_broker.get_quote.return_value = quote

    adapter._broker = mock_broker
    with patch.object(adapter, "_ensure_initialized", new=AsyncMock()):
        ob = await adapter.fetch_order_book("NIFTY")

    assert ob is None


# ---------------------------------------------------------------------------
# get_ltp
# ---------------------------------------------------------------------------

def test_get_ltp_returns_float():
    adapter = _make_adapter()
    mock_broker = _make_mock_broker()
    mock_broker.get_ltp.return_value = 23450.0
    adapter._broker = mock_broker

    ltp = adapter.get_ltp("NIFTY")
    assert ltp == pytest.approx(23450.0)


def test_get_ltp_exception_returns_zero():
    adapter = _make_adapter()
    mock_broker = _make_mock_broker()
    mock_broker.get_ltp.side_effect = RuntimeError("connection error")
    adapter._broker = mock_broker

    ltp = adapter.get_ltp("NIFTY")
    assert ltp == 0.0


# ---------------------------------------------------------------------------
# _exchange_enum
# ---------------------------------------------------------------------------

from app.infrastructure.adapters.dhan_adapter import _exchange_enum


def test_exchange_enum_nse():
    ex = _exchange_enum("NSE")
    assert ex.name == "NSE"


def test_exchange_enum_nfo():
    ex = _exchange_enum("NFO")
    assert ex.name == "NFO"


def test_exchange_enum_mcx():
    ex = _exchange_enum("MCX")
    assert ex.name == "MCX"


def test_exchange_enum_none_defaults_nse():
    ex = _exchange_enum(None)
    assert ex.name == "NSE"


def test_exchange_enum_unknown_defaults_nse():
    ex = _exchange_enum("UNKNOWN")
    assert ex.name == "NSE"


# ---------------------------------------------------------------------------
# _make_instrument
# ---------------------------------------------------------------------------

def test_make_instrument_uses_exchange():
    adapter = _make_adapter(exchange="NFO")
    inst = adapter._make_instrument("NIFTY 20 MAR 23400 CALL")
    assert inst.symbol == "NIFTY 20 MAR 23400 CALL"


# ---------------------------------------------------------------------------
# scan_candidates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_candidates_returns_symbols():
    adapter = _make_adapter()
    result = await adapter.scan_candidates(limit=1)
    assert result == ["NIFTY"]


@pytest.mark.asyncio
async def test_scan_candidates_full_list():
    adapter = _make_adapter()
    result = await adapter.scan_candidates(limit=10)
    assert result == ["NIFTY", "BANKNIFTY"]


# ---------------------------------------------------------------------------
# fetch_history — interval mapping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_history_interval_mapping():
    """'5m' should map to '5' when calling broker.get_historical."""
    adapter = _make_adapter()
    mock_broker = _make_mock_broker()
    mock_broker.get_historical.return_value = pd.DataFrame()
    adapter._broker = mock_broker
    with patch.object(adapter, "_ensure_initialized", new=AsyncMock()):
        await adapter.fetch_history("NIFTY", interval="5m")
    _, kwargs = mock_broker.get_historical.call_args
    assert kwargs["interval"] == "5"


@pytest.mark.asyncio
async def test_fetch_history_none_df_returns_empty():
    adapter = _make_adapter()
    mock_broker = _make_mock_broker()
    mock_broker.get_historical.return_value = None
    adapter._broker = mock_broker
    with patch.object(adapter, "_ensure_initialized", new=AsyncMock()):
        result = await adapter.fetch_history("NIFTY")
    assert result == []


# ---------------------------------------------------------------------------
# stream_full
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stream_full_yields_packets():
    from datetime import datetime
    from shared.entities.models import FullPacket

    adapter = _make_adapter()
    mock_broker = _make_mock_broker()

    async def mock_stream(instruments):
        yield FullPacket(
            symbol="NIFTY", ltp=23500.0, open=23400.0, high=23550.0,
            low=23380.0, close=23500.0, volume=100, oi=0, atp=23450.0,
            total_buy_qty=1000, total_sell_qty=900,
            depth_bids=(), depth_asks=(),
            security_id="1234", exchange_segment="NSE_FNO",
            timestamp=datetime.now(),
        )

    mock_broker.stream_full = mock_stream
    adapter._broker = mock_broker
    with patch.object(adapter, "_ensure_initialized", new=AsyncMock()):
        packets = []
        async for pkt in adapter.stream_full(["NIFTY"]):
            packets.append(pkt)
            break
    assert packets[0]["ltp"] == 23500.0


# ---------------------------------------------------------------------------
# get_option_chain
# ---------------------------------------------------------------------------

def test_get_option_chain_delegates():
    adapter = _make_adapter(exchange="NFO")
    mock_broker = _make_mock_broker()
    mock_broker.get_option_chain.return_value = MagicMock()
    adapter._broker = mock_broker

    result = adapter.get_option_chain("NIFTY", exchange="NFO", expiry_index=0)

    mock_broker.get_option_chain.assert_called_once()
    assert result is not None


def test_get_option_chain_converts_exchange_string():
    adapter = _make_adapter()
    mock_broker = _make_mock_broker()
    mock_broker.get_option_chain.return_value = None
    adapter._broker = mock_broker

    adapter.get_option_chain("NIFTY", exchange="MCX")

    _, kwargs = mock_broker.get_option_chain.call_args
    # Exchange should be the enum, not the string
    assert kwargs["exchange"].name == "MCX"


# ---------------------------------------------------------------------------
# error scenarios
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_order_book_exception_returns_none():
    adapter = _make_adapter()
    mock_broker = _make_mock_broker()
    mock_broker.get_quote.side_effect = ConnectionError("timeout")
    adapter._broker = mock_broker
    with patch.object(adapter, "_ensure_initialized", new=AsyncMock()):
        result = await adapter.fetch_order_book("NIFTY")
    assert result is None
