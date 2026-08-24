import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock, PropertyMock

from app.application.stream_manager import StreamManager
from quant.contracts.ports.market_data import IMarketData

@pytest.fixture
def mock_market_data():
    mock = MagicMock(spec=IMarketData)
    return mock

@pytest.fixture
def stream_manager(mock_market_data):
    # Setting cooldown very low to avoid test delays
    with patch("app.application.stream_manager._DHAN_CONNECT_COOLDOWN", 0):
        sm = StreamManager(market_data=mock_market_data)
        return sm


@pytest.mark.asyncio
async def test_stream_with_reconnect_mcx_mode(stream_manager, mock_market_data):
    """
    Test that when DEFAULT_EXCHANGE == "MCX", depth_task is bypassed.
    """
    stream_manager.set_active_symbols(["CRUDEOIL"])
    stream_manager.set_running(True)

    # Mock the full stream
    async def mock_stream_full(symbols):
        yield {"symbol": "CRUDEOIL", "ltp": 6500.0, "depth_bids": [{"price": 6499.0, "qty": 10}]}
        
        # Stop the generator and force stream_manager loop exit
        stream_manager.set_running(False)

    mock_market_data.stream_full = MagicMock(side_effect=mock_stream_full)

    from app.application import stream_manager as stream_manager_module

    with patch.object(
        type(stream_manager_module.settings),
        "DEFAULT_EXCHANGE",
        new_callable=PropertyMock,
        return_value="MCX",
    ):
        pkts = []
        connect_state = [0.0]
        
        async for pkt in stream_manager.stream_with_reconnect(connect_state):
             pkts.append(pkt)
             
        assert len(pkts) == 1
        assert pkts[0]["ltp"] == 6500.0
        # Assert stream_depth_20 was never called because it's MCX
        if hasattr(mock_market_data, "stream_depth_20"):
             mock_market_data.stream_depth_20.assert_not_called()


@pytest.mark.asyncio
async def test_stream_with_reconnect_nse_mode_dual_stream(stream_manager, mock_market_data):
    """
    Test that when DEFAULT_EXCHANGE == "NSE", the depth worker is created and caches data that is merged into the full stream.
    """
    stream_manager.set_active_symbols(["NIFTY"])
    stream_manager.set_running(True)

    from dataclasses import dataclass
    
    @dataclass
    class DepthLevel:
        price: float
        quantity: int
        
    @dataclass
    class MockDepth:
        symbol: str
        side: str
        levels: list

    # Setup 20-level mock return
    async def mock_stream_depth_20(symbols):
        yield MockDepth(
            symbol="NIFTY", 
            side="bid", 
            levels=[DepthLevel(price=22000.0, quantity=100)] * 20
        )
        yield MockDepth(
            symbol="NIFTY", 
            side="ask", 
            levels=[DepthLevel(price=22010.0, quantity=50)] * 20
        )
        # Yielding to allow test to flush the async task loop
        await asyncio.sleep(0.01)
        
    mock_market_data.stream_depth_20 = MagicMock(side_effect=mock_stream_depth_20)

    # Main stream will wait slightly so depth task can run first
    async def mock_stream_full(symbols):
        await asyncio.sleep(0.05) 
        yield {
            "symbol": "NIFTY", 
            "ltp": 22005.0, 
            # Regular stream has 5 levels, but should be overwritten
            "depth_bids": [{"price": 1.0, "qty": 1}],
            "depth_asks": [{"price": 2.0, "qty": 1}]
        }
        stream_manager.set_running(False)

    mock_market_data.stream_full = MagicMock(side_effect=mock_stream_full)

    from app.application import stream_manager as stream_manager_module

    with patch.object(
        type(stream_manager_module.settings),
        "DEFAULT_EXCHANGE",
        new_callable=PropertyMock,
        return_value="NSE",
    ):
        pkts = []
        connect_state = [0.0]
        
        async for pkt in stream_manager.stream_with_reconnect(connect_state):
             pkts.append(pkt)

        assert len(pkts) == 1
        assert pkts[0]["ltp"] == 22005.0
        
        # Verify 20-level depth was merged safely instead of the mocked 5 level limits
        assert len(pkts[0]["depth_bids"]) == 20
        assert pkts[0]["depth_bids"][0]["price"] == 22000.0
        
        assert len(pkts[0]["depth_asks"]) == 20
        assert pkts[0]["depth_asks"][0]["price"] == 22010.0


@pytest.mark.asyncio
async def test_stream_with_reconnect_polling_fallback(stream_manager, mock_market_data):
    """
    Test the REST polling fallback logic for isolated stability gaps.
    """
    stream_manager.set_active_symbols(["NIFTY"])
    stream_manager._polling_mode = True
    stream_manager.set_running(True)

    async def mock_stream_poll(symbols, poll_interval):
        yield {"symbol": "NIFTY", "ltp": 23000.0, "volume": 0}
        stream_manager._running = False

    mock_market_data.stream_poll = MagicMock(side_effect=mock_stream_poll)

    pkts = []
    connect_state = [0.0]
    
    async for pkt in stream_manager.stream_with_reconnect(connect_state):
         pkts.append(pkt)

    assert len(pkts) == 1
    assert pkts[0]["ltp"] == 23000.0
    # No regular WS logic invoked
    mock_market_data.stream_full.assert_not_called()


@pytest.mark.asyncio
async def test_run_poll_worker_accepts_coroutine_worker(stream_manager):
    """
    Test the unresolved-symbol poll worker path does not expect an async iterator.
    """
    queue = asyncio.Queue()

    async def worker(q):
        await q.put({"symbol": "NIFTY", "ltp": 123.0})

    await stream_manager._run_poll_worker(worker, queue)

    pkt = await queue.get()
    assert pkt["ltp"] == 123.0
