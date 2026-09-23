"""Unit tests for get_lot_size functionality in Dhan broker and adapter."""
from __future__ import annotations

import asyncio
import sys
import os
from unittest.mock import MagicMock

# Ensure project root is on path
_project_root = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter  # noqa: E402
from quant.contracts.ports.market_data import IMarketData  # noqa: E402
from brokers.broker.dhan.application.broker import DhanBroker  # noqa: E402
from brokers.broker.types import Exchange  # noqa: E402

class MockMarketData(IMarketData):
    """Mock implementation of IMarketData to test default get_lot_size."""
    async def scan_candidates(self, limit: int = 6) -> list[str]: return []
    async def fetch_history(self, symbol: str, interval: str = "5m", limit: int = 500): return []
    async def fetch_order_book(self, symbol: str): return None
    def get_ltp(self, symbol: str) -> float: return 0.0
    async def stream_full(self, symbols: list[str]): yield {}
    async def stream_depth_20(self, symbols: list[str]): yield {}

def test_imarketdata_default_lot_size():
    """IMarketData should return 1 as default lot size."""
    mock_md = MockMarketData()
    assert mock_md.get_lot_size("RELIANCE") == 1

def test_dhan_broker_get_lot_size_exists():
    """DhanBroker should have get_lot_size method."""
    mock_config = MagicMock()
    broker = DhanBroker(config=mock_config)
    assert hasattr(broker, "get_lot_size")

def test_dhan_adapter_get_lot_size():
    """DhanMarketDataAdapter.get_lot_size should delegate to the broker's
    option-aware exchange config (bare index instruments carry lot_size=1)."""
    adapter = DhanMarketDataAdapter(
        symbols=["NIFTY"],
        client_id="test",
        access_token="token"
    )
    mock_broker = MagicMock()
    mock_exchange_config = MagicMock()
    mock_exchange_config.get_lot_size.return_value = 65
    mock_broker.get_exchange_config.return_value = mock_exchange_config
    adapter._broker = mock_broker
    
    # Mock ensure_initialized_sync
    adapter.ensure_initialized_sync = MagicMock()
    
    lot_size = adapter.get_lot_size("BANKNIFTY")
    
    assert lot_size == 65
    mock_exchange_config.get_lot_size.assert_called_once_with("BANKNIFTY")

def test_dhan_broker_get_lot_size_logic():
    """Test the internal logic of DhanBroker.get_lot_size fallback with mocks."""
    mock_config = MagicMock()
    broker = DhanBroker(config=mock_config)
    
    mock_instrument = MagicMock()
    mock_instrument.lot_size = 75
    
    # Ensure get_lot_size consumes the async coroutine path and gets deterministic data.
    async def _resolved(_symbol, _exchange=None):
        return mock_instrument

    broker.resolve_symbol = _resolved
    broker._run_async = MagicMock(side_effect=lambda coro: asyncio.run(coro))
    
    lot_size = broker.get_lot_size("UNKNOWN_DERIVATIVE_XYZ", Exchange.NSE)
    
    assert lot_size == 75
    broker._run_async.assert_called_once()


def test_dhan_broker_get_lot_size_mcx_canonical():
    """DhanBroker and DhanExchangeConfig must return canonical lot sizes for MCX contracts."""
    mock_config = MagicMock()
    broker = DhanBroker(config=mock_config)
    cfg = broker.get_exchange_config()

    assert broker.get_lot_size("GOLDM OCT FUT") == 10
    assert broker.get_lot_size("CRUDEOIL SEP FUT") == 100
    assert broker.get_lot_size("SILVERM NOV FUT") == 5
    assert broker.get_lot_size("NATURALGAS SEP FUT") == 1250

    assert cfg.get_lot_size("GOLDM OCT FUT") == 10
    assert cfg.get_lot_size("CRUDEOIL SEP FUT") == 100
    assert cfg.get_lot_size("SILVERM NOV FUT") == 5
    assert cfg.get_lot_size("NATURALGAS SEP FUT") == 1250
