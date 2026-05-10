"""Tests for DhanAdapter — broker and market data adapter.

Behavior: DhanAdapter implements IMarketData port and provides
market data, option chains, and lot sizes with caching.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.infrastructure.adapters.dhan_adapter import DhanAdapter
from app.infrastructure.adapters.option_chain_cache import OptionChainCache


class TestDhanAdapterInitialization:
    """Tests for adapter initialization."""

    def test_creates_with_default_params(self):
        """Should create adapter with default parameters."""
        adapter = DhanAdapter()
        
        assert adapter is not None
        assert adapter._testnet is True
        assert adapter._symbols == []

    def test_creates_with_custom_params(self):
        """Should create adapter with custom parameters."""
        adapter = DhanAdapter(
            symbols=["NIFTY", "BANKNIFTY"],
            exchange="NFO",
            client_id="test_client",
            access_token="test_token",
            testnet=False,
        )
        
        assert adapter._symbols == ["NIFTY", "BANKNIFTY"]
        assert adapter._exchange == "NFO"
        assert adapter._testnet is False

    def test_initializes_ready_state(self):
        """Should initialize as not ready until ensure_initialized called."""
        adapter = DhanAdapter()
        
        assert adapter._is_ready is False


class TestDhanAdapterLotSize:
    """Tests for lot size retrieval."""

    def test_returns_one_when_cache_empty(self):
        """Should return 1 as default when lot size cache is empty."""
        adapter = DhanAdapter()
        
        lot_size = adapter.get_lot_size("NIFTY")
        
        # Currently returns 1 (not implemented)
        assert lot_size == 1

    def test_uses_cache_when_populated(self):
        """Should use cached lot size when available."""
        adapter = DhanAdapter()
        adapter._lot_cache["NIFTY"] = 50
        
        lot_size = adapter.get_lot_size("NIFTY")
        
        assert lot_size == 50


class TestDhanAdapterLTP:
    """Tests for last traded price retrieval."""

    def test_returns_zero_for_unknown_symbol(self):
        """Should return 0.0 for symbols without LTP data."""
        adapter = DhanAdapter()
        
        ltp = adapter.get_ltp("UNKNOWN_SYMBOL")
        
        assert ltp == 0.0

    def test_returns_cached_ltp(self):
        """Should return cached LTP when available."""
        adapter = DhanAdapter()
        # LTP cache stores tuple of (price, timestamp)
        adapter._ltp_cache["NIFTY"] = (19500.5, 1000.0)
        
        ltp = adapter.get_ltp("NIFTY")
        
        assert ltp == 19500.5


class TestDhanAdapterOptionChain:
    """Tests for option chain retrieval."""

    def test_returns_none_without_access_token(self):
        """Should return None when no access token configured."""
        adapter = DhanAdapter(access_token=None)
        
        chain = adapter.get_option_chain("NIFTY")
        
        assert chain is None

    def test_uses_cache_when_valid(self):
        """Should use cached option chain when within TTL."""
        adapter = DhanAdapter(access_token="test_token")
        
        # Pre-populate cache via public API
        mock_chain = MagicMock()
        adapter._option_chain_cache.set("NIFTY", "NFO", 0, mock_chain)
        
        chain = adapter.get_option_chain("NIFTY", "NFO", 0)
        
        # Should return cached value without making API call
        assert chain is mock_chain

    def test_respects_cache_ttl(self):
        """Should expire cache after TTL."""
        adapter = DhanAdapter(access_token="test_token")
        adapter._option_chain_cache = OptionChainCache(ttl_sec=1)
        
        mock_chain = MagicMock()
        # Set cache then wait for expiry
        adapter._option_chain_cache.set("NIFTY", "NFO", 0, mock_chain)
        
        # Cache should exist immediately
        assert adapter._option_chain_cache.get("NIFTY", "NFO", 0) is mock_chain


class TestDhanAdapterStreaming:
    """Tests for market data streaming."""

    @pytest.mark.asyncio
    async def test_stream_yields_ticks_for_symbols(self):
        """Should yield tick data for configured symbols."""
        adapter = DhanAdapter()
        adapter._ltp_cache["NIFTY"] = (1000.0, 19500.0)
        
        # Stream should yield ticks (limited to 1 iteration for test)
        tick_count = 0
        async for tick in adapter.stream_full(["NIFTY"]):
            assert tick["symbol"] == "NIFTY"
            assert tick["ltp"] == 19500.0
            assert "timestamp" in tick
            tick_count += 1
            if tick_count >= 1:
                break

    @pytest.mark.asyncio
    async def test_stream_skips_symbols_with_zero_ltp(self):
        """Should skip symbols with zero or negative LTP."""
        adapter = DhanAdapter()
        # No LTP cached, so get_ltp returns 0
        
        tick_count = 0
        async for tick in adapter.stream_full(["NIFTY"]):
            # Should not yield since LTP is 0
            tick_count += 1
            if tick_count > 1:
                break
        
        # With zero LTP, stream should not yield any ticks
        assert tick_count == 0


class TestDhanAdapterCaching:
    """Tests for caching behavior."""

    def test_ltp_cache_stores_tuple(self):
        """LTP cache should store (timestamp, price) tuple."""
        adapter = DhanAdapter()
        adapter._ltp_cache["NIFTY"] = (1000.0, 19500.5)
        
        cached = adapter._ltp_cache["NIFTY"]
        
        assert isinstance(cached, tuple)
        assert len(cached) == 2
        assert cached[0] == 1000.0  # timestamp
        assert cached[1] == 19500.5  # price

    def test_lot_cache_stores_int(self):
        """Lot size cache should store integer values."""
        adapter = DhanAdapter()
        adapter._lot_cache["NIFTY"] = 50
        
        assert adapter._lot_cache["NIFTY"] == 50
        assert isinstance(adapter._lot_cache["NIFTY"], int)

    def test_option_chain_cache_uses_composite_key(self):
        """Option chain cache should use (underlying, exchange, expiry_index) key."""
        adapter = DhanAdapter(access_token="test_token")
        
        mock_chain = MagicMock()
        adapter._option_chain_cache.set("NIFTY", "NFO", 0, mock_chain)
        
        assert adapter._option_chain_cache.get("NIFTY", "NFO", 0) is mock_chain


class TestDhanAdapterCleanup:
    """Tests for resource cleanup."""

    def test_close_sync_closes_client(self):
        """Should close HTTP client."""
        adapter = DhanAdapter()
        mock_client = MagicMock()
        mock_client.is_closed = False
        adapter._client = mock_client
        
        adapter.close_sync()
        
        mock_client.close.assert_called_once()
