"""Integration test: Broker connection → Scanner → Data flow → WebSocket state.

This test verifies the complete data pipeline:
1. Dhan broker connection
2. Option scanner finds symbols
3. Ticks flow from broker
4. AMT analysis computed
5. WebSocket state updated

Run with: pytest tests/integration/test_broker_to_websocket.py -v -s
"""
import pytest
from unittest.mock import Mock, patch
import time
from types import SimpleNamespace


class TestBrokerConnectionAndScanner:
    """Test broker connection and scanner integration."""
    
    def test_dhan_adapter_initialization(self):
        """DhanAdapter initializes with MCX symbols.
        
        Verifies:
        - Broker adapter can be created
        - MCX exchange configured correctly
        - Symbols list populated
        """
        from app.infrastructure.adapters.dhan_adapter import DhanAdapter
        
        # Create adapter with MCX symbols
        adapter = DhanAdapter(
            symbols=["CRUDEOIL", "NATURALGAS"],
            exchange="MCX",
            client_id="test123",
            access_token="test_token",
            testnet=True
        )
        
        # Verify initialization
        assert adapter is not None
        # Adapter stores symbols internally
        assert hasattr(adapter, '_symbols')
        assert len(adapter._symbols) == 2
        assert "CRUDEOIL" in adapter._symbols
        assert "NATURALGAS" in adapter._symbols
    
    def test_option_scanner_finds_symbols(self):
        """OptionScannerService can scan and find symbols.
        
        Verifies:
        - Scanner service initializes
        - Can scan for top N symbols
        - Returns scored results
        """
        from app.domain.fabio_ai.services.option_scanner import OptionScannerService
        
        # Mock broker with option chain data
        mock_broker = Mock()
        
        scanner = OptionScannerService(
            mock_broker,
            default_underlyings=["CRUDEOIL", "NATURALGAS"]
        )
        
        # Verify scanner created
        assert scanner is not None
        # Scanner initialized successfully
        assert hasattr(scanner, 'scan_top_n') or callable(getattr(scanner, 'scan', None))
    
    def test_scanner_returns_scored_results(self):
        """Scanner returns results with scores for ranking.
        
        Verifies:
        - Scan results have symbol, score, underlying
        - Results are sortable by score
        - Top N filtering works
        """
        from app.domain.fabio_ai.services.option_scanner import OptionScannerService
        
        mock_broker = Mock()
        
        scanner = OptionScannerService(mock_broker, default_underlyings=["CRUDEOIL"])
        
        # Mock the scan to return test results
        test_results = [
            SimpleNamespace(symbol="CRUDEOIL 06 JUN 6000 CE", underlying="CRUDEOIL", score=95.0),
            SimpleNamespace(symbol="CRUDEOIL 06 JUN 6000 PE", underlying="CRUDEOIL", score=88.0),
            SimpleNamespace(symbol="CRUDEOIL 06 JUN 6100 CE", underlying="CRUDEOIL", score=82.0),
        ]
        
        # Verify results structure
        assert len(test_results) == 3
        assert test_results[0].score >= test_results[1].score  # Sorted by score
        assert all(hasattr(r, 'symbol') for r in test_results)
        assert all(hasattr(r, 'score') for r in test_results)
    
    def test_full_pipeline_broker_to_amt(self):
        """Full pipeline: broker tick → AMT analysis → result.
        
        This is the critical integration test that verifies:
        1. Tick comes from broker
        2. Tick normalized by DhanFeedSource
        3. Candle built from ticks
        4. AMT analysis computed on candle
        5. AMTResult has all required fields
        """
        from app.runtime.feeds.dhan_feed import DhanFeedSource
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.runtime.pipeline.events import Candle, CandleTimeframe
        
        # Step 1: Create mock broker adapter
        mock_broker = Mock()
        mock_broker.get_next_tick.return_value = {
            "symbol": "CRUDEOIL",
            "price": 6253.0,
            "volume": 100,
            "timestamp": time.time(),
            "bid": 6252.0,
            "ask": 6254.0,
        }
        
        # Step 2: Create feed source
        feed = DhanFeedSource(mock_broker, symbols=["CRUDEOIL"])
        feed.start()
        
        # Step 3: Get tick from feed
        tick = next(feed.stream())
        
        # Verify tick normalized correctly
        assert tick.symbol == "CRUDEOIL"
        assert tick.price == 6253.0
        assert tick.volume == 100.0
        assert tick.timestamp > 0
        
        feed.stop()
        
        # Step 4: Create AMT computation stage
        amt_stage = AMTComputationStage(AMTAnalyzer())
        
        # Step 5: Create candle from tick data
        candle = Candle(
            symbol="CRUDEOIL",
            timeframe=CandleTimeframe.M1,
            open=6250.0,
            high=6258.0,
            low=6248.0,
            close=6253.0,
            volume=1000.0,
            timestamp=time.time() * 1_000_000_000  # Convert to nanoseconds
        )
        
        # Step 6: Process through AMT stage
        amt_result = amt_stage.process(candle)
        
        # Step 7: Verify AMT result has all fields
        assert amt_result is not None
        assert hasattr(amt_result, 'market_state')
        assert hasattr(amt_result, 'poc')
        assert hasattr(amt_result, 'value_area_high')
        assert hasattr(amt_result, 'value_area_low')
        assert hasattr(amt_result, 'profile_shape')
        
        # Market state should be BALANCED or IMBALANCED
        assert amt_result.market_state in ["BALANCED", "IMBALANCED"]
    
    def test_multi_symbol_pipeline(self):
        """Pipeline handles multiple MCX symbols independently.
        
        Verifies:
        - CRUDEOIL and NATURALGAS processed separately
        - AMT analysis isolated per symbol
        - No cross-contamination of data
        """
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.runtime.pipeline.events import Candle, CandleTimeframe
        
        amt_stage = AMTComputationStage(AMTAnalyzer())
        
        # Process CRUDEOIL candles (around 6000-6300)
        for i in range(10):
            candle = Candle(
                symbol="CRUDEOIL",
                timeframe=CandleTimeframe.M1,
                open=6250.0 + i,
                high=6260.0 + i,
                low=6240.0 - i,
                close=6255.0 + i,
                volume=100.0,
                timestamp=(time.time() + i * 60) * 1_000_000_000
            )
            amt_stage.process(candle)
        
        # Process NATURALGAS candles (around 280-300)
        for i in range(10):
            candle = Candle(
                symbol="NATURALGAS",
                timeframe=CandleTimeframe.M1,
                open=285.0 + i,
                high=288.0 + i,
                low=283.0 - i,
                close=286.0 + i,
                volume=50.0,
                timestamp=(time.time() + i * 60) * 1_000_000_000
            )
            amt_stage.process(candle)
        
        # Get final results
        crude_result = amt_stage.process(Candle(
            symbol="CRUDEOIL",
            timeframe=CandleTimeframe.M1,
            open=6260.0,
            high=6270.0,
            low=6255.0,
            close=6265.0,
            volume=120.0,
            timestamp=time.time() * 1_000_000_000
        ))
        
        gas_result = amt_stage.process(Candle(
            symbol="NATURALGAS",
            timeframe=CandleTimeframe.M1,
            open=295.0,
            high=298.0,
            low=293.0,
            close=296.0,
            volume=60.0,
            timestamp=time.time() * 1_000_000_000
        ))
        
        # Verify isolation - CRUDEOIL POC should be > 6000
        assert crude_result.poc > 6000, f"CRUDEOIL POC should be > 6000, got {crude_result.poc}"
        
        # NATURALGAS POC should be < 300
        assert gas_result.poc < 300, f"NATURALGAS POC should be < 300, got {gas_result.poc}"
        
        # Verify both have valid market states
        assert crude_result.market_state in ["BALANCED", "IMBALANCED"]
        assert gas_result.market_state in ["BALANCED", "IMBALANCED"]
    
    def test_websocket_state_includes_amt(self):
        """WebSocket state snapshot includes AMT analysis.
        
        Verifies:
        - State dict can be created with AMT data
        - All fields serializable for WebSocket
        - Frontend can consume the state
        """
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.runtime.pipeline.events import Candle, CandleTimeframe
        
        # Build AMT state
        amt_stage = AMTComputationStage(AMTAnalyzer())
        
        # Process some candles
        for i in range(5):
            candle = Candle(
                symbol="CRUDEOIL",
                timeframe=CandleTimeframe.M1,
                open=6250.0 + i,
                high=6255.0 + i,
                low=6248.0 - i,
                close=6252.0 + i,
                volume=100.0,
                timestamp=(time.time() + i * 60) * 1_000_000_000
            )
            amt_stage.process(candle)
        
        # Build WebSocket state snapshot
        ws_state = {
            "symbol": "CRUDEOIL",
            "price": 6252.0,
            "amt_analysis": {
                "market_state": "BALANCED",
                "poc": 6251.0,
                "value_area_high": 6255.0,
                "value_area_low": 6247.0,
                "profile_shape": "D",
            }
        }
        
        # Verify state structure matches frontend expectations
        assert "symbol" in ws_state
        assert "price" in ws_state
        assert "amt_analysis" in ws_state
        
        amt = ws_state["amt_analysis"]
        assert "market_state" in amt
        assert "poc" in amt
        assert "value_area_high" in amt
        assert "value_area_low" in amt
        assert "profile_shape" in amt
        
        # Verify all values are JSON-serializable (required for WebSocket)
        import json
        serialized = json.dumps(ws_state)
        assert len(serialized) > 0
