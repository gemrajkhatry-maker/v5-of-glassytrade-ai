"""Option-chain fetch coalescing on DhanMarketDataAdapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


def test_option_chain_cache_reuses_single_broker_call():
    os.environ["OPTION_CHAIN_CACHE_TTL_SEC"] = "60"
    from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter

    ad = DhanMarketDataAdapter(client_id="1", access_token="t")
    mock_chain = object()
    mock_broker = MagicMock()
    mock_broker.get_option_chain.return_value = mock_chain
    ad._broker = mock_broker
    ad._initialized = True

    with patch.object(ad, "ensure_initialized_sync", lambda: None):
        c1 = ad.get_option_chain("NIFTY", "NFO", 0)
        c2 = ad.get_option_chain("NIFTY", "NFO", 0)

    assert c1 is mock_chain
    assert c2 is mock_chain
    assert mock_broker.get_option_chain.call_count == 1


def test_option_chain_cache_disabled_when_ttl_zero():
    os.environ["OPTION_CHAIN_CACHE_TTL_SEC"] = "0"
    from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter

    ad = DhanMarketDataAdapter(client_id="1", access_token="t")
    mock_chain = object()
    mock_broker = MagicMock()
    mock_broker.get_option_chain.return_value = mock_chain
    ad._broker = mock_broker
    ad._initialized = True

    with patch.object(ad, "ensure_initialized_sync", lambda: None):
        ad.get_option_chain("NIFTY", "NFO", 0)
        ad.get_option_chain("NIFTY", "NFO", 0)

    assert mock_broker.get_option_chain.call_count == 2
