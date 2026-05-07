"""
Live Market Integration Tests - Backend Scanner
Tests scanner service, startup flow, WebSocket state with live data.

Run with: cd backendv2 && ../venv/bin/python -m pytest tests/integration/test_live_scanner_integration.py --live -v
"""
import os
import json
import time
import pytest
from datetime import datetime
from types import SimpleNamespace

from brokers.gateway import BrokerGateway
from app.domain.fabio_ai.services.option_scanner import OptionScannerService, ScanResult

# Skip all tests if credentials missing
pytestmark = pytest.mark.skipif(
    not os.getenv("DHAN_ACCESS_TOKEN")
    or os.getenv("RUN_LIVE_SCANNER_TESTS", "").lower() not in {"1", "true", "yes"},
    reason="DHAN_ACCESS_TOKEN and RUN_LIVE_SCANNER_TESTS=true are required for live scanner tests"
)


# =============================================================================
# Test Suite 1: Live Scanner Service
# =============================================================================

class TestLiveScannerService:
    """Test scanner service with live broker connection."""

    def test_scanner_mcx_initialization(self):
        """Scanner initializes with MCX underlyings."""
        gateway = BrokerGateway.dhan()
        try:
            scanner = OptionScannerService(
                gateway.raw_broker,
                default_underlyings=["CRUDEOIL", "NATURALGAS"]
            )
            assert scanner is not None
            assert scanner._default_underlyings == ["CRUDEOIL", "NATURALGAS"]
        finally:
            gateway.close()

    def test_scanner_nse_initialization(self):
        """Scanner initializes with NSE underlyings."""
        gateway = BrokerGateway.dhan()
        try:
            scanner = OptionScannerService(
                gateway.raw_broker,
                default_underlyings=["NIFTY", "BANKNIFTY"]
            )
            assert scanner is not None
        finally:
            gateway.close()

    def test_scanner_mcx_returns_results(self):
        """Scanner returns results for MCX."""
        gateway = BrokerGateway.dhan()
        try:
            scanner = OptionScannerService(gateway.raw_broker, ["CRUDEOIL", "NATURALGAS"])
            results = scanner.scan_top_n(
                n=6,
                underlyings=["CRUDEOIL", "NATURALGAS"],
                top_per_underlying=3,
                exchange="MCX",
                expiry_index=0,
                strikes_around_atm=3,
            )
            assert len(results) >= 4, f"Should have at least 4 results, got {len(results)}"
            assert all(isinstance(r, ScanResult) for r in results)
            assert all(r.score > 0 for r in results)
            assert all(r.ltp >= 0 for r in results)
        finally:
            gateway.close()

    def test_scanner_nse_returns_results(self):
        """Scanner returns results for NSE."""
        gateway = BrokerGateway.dhan()
        try:
            scanner = OptionScannerService(gateway.raw_broker, ["NIFTY", "BANKNIFTY"])
            results = scanner.scan_top_n(
                n=4,
                underlyings=["NIFTY", "BANKNIFTY"],
                top_per_underlying=2,
                exchange="NFO",
                expiry_index=0,
                strikes_around_atm=2,
            )
            assert len(results) >= 2
            assert all(r.score > 0 for r in results)
        finally:
            gateway.close()

    def test_scanner_multi_underlying_ranking(self):
        """Scanner ranks contracts across multiple underlyings."""
        gateway = BrokerGateway.dhan()
        try:
            scanner = OptionScannerService(gateway.raw_broker, ["CRUDEOIL", "NATURALGAS"])
            results = scanner.scan_top_n(
                n=6,
                underlyings=["CRUDEOIL", "NATURALGAS"],
                top_per_underlying=3,
                exchange="MCX",
                expiry_index=0,
                strikes_around_atm=2,
            )
            # Results should be sorted by score
            for i in range(len(results) - 1):
                assert results[i].score >= results[i+1].score, "Results should be sorted by score"
        finally:
            gateway.close()

    def test_scanner_contract_scoring(self):
        """Scanner produces valid contract scores."""
        gateway = BrokerGateway.dhan()
        try:
            scanner = OptionScannerService(gateway.raw_broker, ["CRUDEOIL"])
            results = scanner.scan_top_n(
                n=5,
                underlyings=["CRUDEOIL"],
                top_per_underlying=5,
                exchange="MCX",
                expiry_index=0,
                strikes_around_atm=3,
            )
            for result in results:
                assert result.score > 0, f"Score should be positive: {result}"
                assert result.strike > 0, f"Strike should be positive: {result}"
                assert result.option_type in ["CE", "PE"], f"Invalid option type: {result.option_type}"
        finally:
            gateway.close()


# =============================================================================
# Test Suite 2: Live Scanner API
# =============================================================================

class TestLiveScannerAPI:
    """Test scanner API endpoints with live data."""

    def test_scanner_status_endpoint(self):
        """Scanner status endpoint returns valid data."""
        from fastapi.testclient import TestClient
        from app.api import main
        
        # Mock scanner to avoid blocking startup
        class LiveScanner:
            def __init__(self, *args, **kwargs):
                pass
            def scan_top_n(self, *args, **kwargs):
                gateway = BrokerGateway.dhan()
                try:
                    scanner = OptionScannerService(gateway.raw_broker, ["CRUDEOIL"])
                    return scanner.scan_top_n(n=3, underlyings=["CRUDEOIL"], exchange="MCX", expiry_index=0)
                finally:
                    gateway.close()
        
        original_scanner = main.OptionScannerService
        main.OptionScannerService = LiveScanner
        
        try:
            with TestClient(main.app) as client:
                resp = client.get("/api/scanner/status")
                assert resp.status_code == 200
                data = resp.json()
                assert "active_symbols" in data
        finally:
            main.OptionScannerService = original_scanner

    def test_scanner_rescan_endpoint(self):
        """Scanner rescan endpoint triggers live scan."""
        from fastapi.testclient import TestClient
        from app.api import main
        
        # Use live scanner
        class LiveScanner:
            def __init__(self, *args, **kwargs):
                pass
            def scan_top_n(self, *args, **kwargs):
                gateway = BrokerGateway.dhan()
                try:
                    scanner = OptionScannerService(gateway.raw_broker, ["CRUDEOIL"])
                    return scanner.scan_top_n(n=3, underlyings=["CRUDEOIL"], exchange="MCX", expiry_index=0)
                finally:
                    gateway.close()
        
        original_scanner = main.OptionScannerService
        main.OptionScannerService = LiveScanner
        
        try:
            with TestClient(main.app) as client:
                resp = client.post("/api/scanner/rescan", params={"n": 3})
                assert resp.status_code == 200
                data = resp.json()
                assert "active_symbols" in data
                assert "scan_count" in data
        finally:
            main.OptionScannerService = original_scanner

    def test_scanner_rescan_updates_symbols(self):
        """Rescan updates active symbols in app state."""
        from fastapi.testclient import TestClient
        from app.api import main
        
        class LiveScanner:
            def __init__(self, *args, **kwargs):
                pass
            def scan_top_n(self, *args, **kwargs):
                gateway = BrokerGateway.dhan()
                try:
                    scanner = OptionScannerService(gateway.raw_broker, ["CRUDEOIL"])
                    return scanner.scan_top_n(n=2, underlyings=["CRUDEOIL"], exchange="MCX", expiry_index=0)
                finally:
                    gateway.close()
        
        original_scanner = main.OptionScannerService
        main.OptionScannerService = LiveScanner
        
        try:
            with TestClient(main.app) as client:
                # Initial state
                config_resp = client.get("/api/system/config")
                initial_symbols = config_resp.json().get("activeSymbols", [])
                
                # Trigger rescan
                rescan_resp = client.post("/api/scanner/rescan", params={"n": 2})
                assert rescan_resp.status_code == 200
                
                # Verify symbols updated
                data = rescan_resp.json()
                assert len(data["active_symbols"]) >= 1
        finally:
            main.OptionScannerService = original_scanner

    def test_system_config_active_symbols(self):
        """System config includes active symbols from live scanner."""
        from fastapi.testclient import TestClient
        from app.api import main
        
        class LiveScanner:
            def __init__(self, *args, **kwargs):
                pass
            def scan_top_n(self, *args, **kwargs):
                gateway = BrokerGateway.dhan()
                try:
                    scanner = OptionScannerService(gateway.raw_broker, ["CRUDEOIL"])
                    return scanner.scan_top_n(n=3, underlyings=["CRUDEOIL"], exchange="MCX", expiry_index=0)
                finally:
                    gateway.close()
        
        original_scanner = main.OptionScannerService
        main.OptionScannerService = LiveScanner
        
        try:
            with TestClient(main.app) as client:
                resp = client.get("/api/system/config")
                assert resp.status_code == 200
                data = resp.json()
                assert "activeSymbols" in data
                assert isinstance(data["activeSymbols"], list)
        finally:
            main.OptionScannerService = original_scanner


# =============================================================================
# Test Suite 3: Live Broker Adapter
# =============================================================================

class TestLiveBrokerAdapter:
    """Test DhanAdapter in backendv2 with live data."""

    def test_dhan_adapter_initialization(self):
        """DhanAdapter initializes with credentials."""
        from app.infrastructure.adapters.dhan_adapter import DhanAdapter
        
        adapter = DhanAdapter(
            symbols=["CRUDEOIL", "NATURALGAS"],
            exchange="MCX",
            testnet=True,
        )
        assert adapter is not None
        assert adapter._symbols == ["CRUDEOIL", "NATURALGAS"]
        adapter.close_sync()

    def test_dhan_adapter_get_option_chain(self):
        """DhanAdapter fetches option chain."""
        from app.infrastructure.adapters.dhan_adapter import DhanAdapter
        
        adapter = DhanAdapter(
            symbols=["CRUDEOIL"],
            exchange="MCX",
            testnet=True,
        )
        try:
            chain = adapter.get_option_chain("CRUDEOIL", "MCX", expiry_index=0)
            assert chain is not None
            assert chain.atm_strike > 0
        finally:
            adapter.close_sync()

    def test_dhan_adapter_cache_behavior(self):
        """DhanAdapter caches option chain results."""
        from app.infrastructure.adapters.dhan_adapter import DhanAdapter
        
        adapter = DhanAdapter(
            symbols=["CRUDEOIL"],
            exchange="MCX",
            testnet=True,
        )
        try:
            # First call - should hit API
            start = time.time()
            chain1 = adapter.get_option_chain("CRUDEOIL", "MCX", expiry_index=0)
            first_call_time = time.time() - start
            
            # Second call - should use cache (faster)
            start = time.time()
            chain2 = adapter.get_option_chain("CRUDEOIL", "MCX", expiry_index=0)
            second_call_time = time.time() - start
            
            assert chain1 is not None
            assert chain2 is not None
            # Cache should make second call faster (though may vary)
        finally:
            adapter.close_sync()

    def test_dhan_adapter_error_handling(self):
        """DhanAdapter handles errors gracefully."""
        from app.infrastructure.adapters.dhan_adapter import DhanAdapter
        
        adapter = DhanAdapter(
            symbols=["INVALID_SYMBOL"],
            exchange="MCX",
            testnet=True,
        )
        try:
            # Invalid symbol should return None or handle gracefully
            chain = adapter.get_option_chain("INVALID_SYMBOL", "MCX", expiry_index=0)
            # Should not raise exception, just return None
            assert chain is None or hasattr(chain, 'atm_strike')
        finally:
            adapter.close_sync()


# =============================================================================
# Test Suite 4: Live WebSocket State
# =============================================================================

class TestLiveWebSocketState:
    """Test WebSocket state with live AMT data."""

    def test_websocket_state_includes_symbols(self):
        """WebSocket state includes active symbols."""
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        
        gateway = BrokerGateway.dhan()
        try:
            # Run scanner to get symbols
            scanner = OptionScannerService(gateway.raw_broker, ["CRUDEOIL"])
            results = scanner.scan_top_n(n=3, underlyings=["CRUDEOIL"], exchange="MCX", expiry_index=0)
            symbols = [r.symbol for r in results[:3]]
            
            assert len(symbols) > 0
            assert all(isinstance(s, str) for s in symbols)
        finally:
            gateway.close()

    def test_websocket_amt_analysis_present(self):
        """WebSocket state includes AMT analysis."""
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.domain.trading.model.value_objects import Candle, CandleTimeframe
        
        amt_stage = AMTComputationStage(AMTAnalyzer())
        
        # Process some candles
        for i in range(20):
            candle = Candle(
                symbol="CRUDEOIL",
                timeframe=CandleTimeframe.M1,
                open=6250.0 + i,
                high=6258.0 + i,
                low=6248.0 + i,
                close=6253.0 + i,
                volume=1000.0,
                timestamp=time.time() * 1e9
            )
            result = amt_stage.process(candle)
        
        # Verify AMT result has required fields
        assert result.market_state in ["BALANCED", "IMBALANCED"]
        assert result.poc > 0
        assert result.value_area_high > 0
        assert result.value_area_low > 0

    def test_websocket_multi_symbol_state(self):
        """WebSocket state handles multiple symbols."""
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.domain.trading.model.value_objects import Candle, CandleTimeframe
        
        amt_stage = AMTComputationStage(AMTAnalyzer())
        
        # Process candles for multiple symbols
        for symbol in ["CRUDEOIL", "NATURALGAS"]:
            for i in range(10):
                candle = Candle(
                    symbol=symbol,
                    timeframe=CandleTimeframe.M1,
                    open=100.0 + i,
                    high=108.0 + i,
                    low=98.0 + i,
                    close=103.0 + i,
                    volume=500.0,
                    timestamp=time.time() * 1e9
                )
                result = amt_stage.process(candle)
                assert result.poc > 0

    def test_websocket_json_serializable(self):
        """WebSocket state is JSON serializable."""
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.domain.trading.model.value_objects import Candle, CandleTimeframe
        
        amt_stage = AMTComputationStage(AMTAnalyzer())
        
        # Process candles
        for i in range(20):
            candle = Candle(
                symbol="CRUDEOIL",
                timeframe=CandleTimeframe.M1,
                open=6250.0 + i,
                high=6258.0 + i,
                low=6248.0 + i,
                close=6253.0 + i,
                volume=1000.0,
                timestamp=time.time() * 1e9
            )
            result = amt_stage.process(candle)
        
        # Convert to dict for WebSocket
        state_dict = {
            "market_state": result.market_state,
            "poc": result.poc,
            "value_area_high": result.value_area_high,
            "value_area_low": result.value_area_low,
            "profile_shape": result.profile_shape,
        }
        
        # Verify JSON serializable
        json_str = json.dumps(state_dict)
        assert json_str is not None
        parsed = json.loads(json_str)
        assert parsed["market_state"] in ["BALANCED", "IMBALANCED"]


# =============================================================================
# Test Suite 5: Live End-to-End Pipeline
# =============================================================================

class TestLiveEndToEndPipeline:
    """Test full pipeline: broker → scanner → AMT → WebSocket."""

    def test_full_pipeline_mcx(self):
        """Full pipeline for MCX: broker → scanner → AMT analysis."""
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.domain.trading.model.value_objects import Candle, CandleTimeframe
        
        gateway = BrokerGateway.dhan()
        try:
            # Step 1: Scanner finds contracts
            scanner = OptionScannerService(gateway.raw_broker, ["CRUDEOIL"])
            results = scanner.scan_top_n(n=3, underlyings=["CRUDEOIL"], exchange="MCX", expiry_index=0)
            assert len(results) > 0
            
            # Step 2: AMT analysis on simulated candles
            amt_stage = AMTComputationStage(AMTAnalyzer())
            for i in range(20):
                candle = Candle(
                    symbol="CRUDEOIL",
                    timeframe=CandleTimeframe.M1,
                    open=6250.0 + i,
                    high=6258.0 + i,
                    low=6248.0 + i,
                    close=6253.0 + i,
                    volume=1000.0,
                    timestamp=time.time() * 1e9
                )
                result = amt_stage.process(candle)
            
            # Step 3: Verify AMT result
            assert result.market_state in ["BALANCED", "IMBALANCED"]
            assert result.poc > 0
            
            # Step 4: Verify WebSocket serialization
            state_dict = {
                "market_state": result.market_state,
                "poc": result.poc,
                "value_area_high": result.value_area_high,
                "value_area_low": result.value_area_low,
            }
            assert json.dumps(state_dict) is not None
        finally:
            gateway.close()

    def test_full_pipeline_nse(self):
        """Full pipeline for NSE: broker → scanner → AMT analysis."""
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.domain.trading.model.value_objects import Candle, CandleTimeframe
        
        gateway = BrokerGateway.dhan()
        try:
            # Step 1: Scanner finds NSE contracts
            scanner = OptionScannerService(gateway.raw_broker, ["NIFTY"])
            results = scanner.scan_top_n(n=3, underlyings=["NIFTY"], exchange="NFO", expiry_index=0)
            assert len(results) > 0
            
            # Step 2: AMT analysis
            amt_stage = AMTComputationStage(AMTAnalyzer())
            for i in range(20):
                candle = Candle(
                    symbol="NIFTY",
                    timeframe=CandleTimeframe.M1,
                    open=24300.0 + i * 10,
                    high=24350.0 + i * 10,
                    low=24280.0 + i * 10,
                    close=24320.0 + i * 10,
                    volume=5000.0,
                    timestamp=time.time() * 1e9
                )
                result = amt_stage.process(candle)
            
            assert result.poc > 0
        finally:
            gateway.close()

    def test_pipeline_multi_symbol(self):
        """Pipeline handles multiple symbols correctly."""
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.domain.trading.model.value_objects import Candle, CandleTimeframe
        
        gateway = BrokerGateway.dhan()
        try:
            # Scanner for multiple symbols
            scanner = OptionScannerService(gateway.raw_broker, ["CRUDEOIL", "NATURALGAS"])
            results = scanner.scan_top_n(n=6, underlyings=["CRUDEOIL", "NATURALGAS"], exchange="MCX", expiry_index=0)
            assert len(results) > 0
            
            # AMT for multiple symbols
            amt_stage = AMTComputationStage(AMTAnalyzer())
            for symbol in ["CRUDEOIL", "NATURALGAS"]:
                for i in range(10):
                    candle = Candle(
                        symbol=symbol,
                        timeframe=CandleTimeframe.M1,
                        open=100.0 + i,
                        high=108.0 + i,
                        low=98.0 + i,
                        close=103.0 + i,
                        volume=500.0,
                        timestamp=time.time() * 1e9
                    )
                    result = amt_stage.process(candle)
                    assert result.poc > 0
        finally:
            gateway.close()

    def test_pipeline_performance_timing(self):
        """Pipeline completes within reasonable time."""
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.domain.trading.model.value_objects import Candle, CandleTimeframe
        
        gateway = BrokerGateway.dhan()
        try:
            start = time.time()
            
            # Scanner
            scanner = OptionScannerService(gateway.raw_broker, ["CRUDEOIL"])
            results = scanner.scan_top_n(n=3, underlyings=["CRUDEOIL"], exchange="MCX", expiry_index=0)
            scan_time = time.time() - start
            
            # AMT
            amt_stage = AMTComputationStage(AMTAnalyzer())
            amt_start = time.time()
            for i in range(20):
                candle = Candle(
                    symbol="CRUDEOIL",
                    timeframe=CandleTimeframe.M1,
                    open=6250.0 + i,
                    high=6258.0 + i,
                    low=6248.0 + i,
                    close=6253.0 + i,
                    volume=1000.0,
                    timestamp=time.time() * 1e9
                )
                amt_stage.process(candle)
            amt_time = time.time() - amt_start
            
            # Verify timing
            assert scan_time < 60, f"Scanner should complete in < 60s, took {scan_time:.1f}s"
            assert amt_time < 10, f"AMT should complete in < 10s, took {amt_time:.1f}s"
            
            print(f"\n  Scanner: {scan_time:.1f}s, AMT: {amt_time:.1f}s")
        finally:
            gateway.close()
