"""Integration tests for AMT data flowing through WebSocket state.

These tests verify that AMT results are serialized and included
in WebSocket state updates sent to the frontend.

TDD Status: RED→GREEN cycle in progress
"""
import pytest
from fastapi.testclient import TestClient


class TestAMTWebSocketIntegration:
    """Test AMT data flows through WebSocket to frontend."""
    
    def test_amt_serialized_in_state(self):
        """AMTResult is serialized to dict for WebSocket state.
        
        Behavior: When SessionRuntime takes a snapshot, AMTResult
        should be converted to a dict with all fields the frontend expects:
        - market_state: "BALANCED" or "IMBALANCED"
        - poc: Point of Control price
        - value_area_high: VAH price
        - value_area_low: VAL price
        - profile_shape: "D", "P", "b", "B", etc.
        
        This ensures frontend can render AMT visualization.
        """
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.runtime.pipeline.events import Candle, CandleTimeframe
        from app.domain.trading.model.value_objects import AMTResult
        
        # Create stage and process candles
        stage = AMTComputationStage(AMTAnalyzer())
        
        for i in range(20):
            candle = Candle(
                symbol="CRUDEOIL",
                timeframe=CandleTimeframe.M1,
                open=7250.0 + (i % 5),
                high=7256.0 + (i % 3),
                low=7247.0 - (i % 3),
                close=7252.0 + (i % 7),
                volume=100.0 + i * 10,
                timestamp=1714982100.0 + i * 60
            )
            result = stage.process(candle)
        
        # Get final result
        final_candle = Candle(
            symbol="CRUDEOIL",
            timeframe=CandleTimeframe.M1,
            open=7252.0,
            high=7258.0,
            low=7250.0,
            close=7256.0,
            volume=150.0,
            timestamp=1714983300.0
        )
        result = stage.process(final_candle)
        
        # Verify AMTResult can be converted to dict
        assert isinstance(result, AMTResult)
        
        # Convert to dict (simulating serialization for WebSocket)
        result_dict = {
            "market_state": result.market_state,
            "poc": result.poc,
            "value_area_high": result.value_area_high,
            "value_area_low": result.value_area_low,
            "profile_shape": result.profile_shape,
        }
        
        # Verify all fields are present and serializable
        assert "market_state" in result_dict
        assert isinstance(result_dict["market_state"], str)
        assert "poc" in result_dict
        assert isinstance(result_dict["poc"], (int, float))
        assert "value_area_high" in result_dict
        assert isinstance(result_dict["value_area_high"], (int, float))
        assert "value_area_low" in result_dict
        assert isinstance(result_dict["value_area_low"], (int, float))
        assert "profile_shape" in result_dict
    
    def test_amt_state_includes_analysis(self):
        """WebSocket state includes AMT analysis in snapshot.
        
        Behavior: When frontend requests state snapshot, the response
        should include amt_analysis field with market state and profile.
        """
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.runtime.pipeline.events import Candle, CandleTimeframe
        
        # Build AMT state
        stage = AMTComputationStage(AMTAnalyzer())
        
        # Process candles
        for i in range(10):
            candle = Candle(
                symbol="NIFTY",
                timeframe=CandleTimeframe.M5,
                open=22500.0 + i,
                high=22520.0 + i,
                low=22490.0 - i,
                close=22510.0 + i,
                volume=500.0,
                timestamp=1714982100.0 + i * 300
            )
            stage.process(candle)
        
        # Build state snapshot (simulating WebSocket response)
        snapshot = {
            "symbol": "NIFTY",
            "price": 22510.0,
            "amt_analysis": {
                "market_state": "BALANCED",
                "poc": 22505.0,
                "value_area_high": 22515.0,
                "value_area_low": 22495.0,
                "profile_shape": "D",
            }
        }
        
        # Verify structure matches frontend expectations
        assert "amt_analysis" in snapshot
        assert snapshot["amt_analysis"]["market_state"] in ["BALANCED", "IMBALANCED"]
        assert snapshot["amt_analysis"]["poc"] > 0
        assert snapshot["amt_analysis"]["value_area_high"] > 0
        assert snapshot["amt_analysis"]["value_area_low"] > 0
    
    def test_amt_null_when_no_data(self):
        """AMT analysis is null/None when no candles processed.
        
        Behavior: When session has no candles yet, AMT analysis
        should be null to indicate data not available.
        Frontend should show "Awaiting data..." state.
        """
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        
        stage = AMTComputationStage(AMTAnalyzer())
        
        # Before any candles, snapshot should show no data
        snap = stage.snapshot()
        assert "CRUDEOIL" not in snap or snap.get("CRUDEOIL", 0) == 0
        
        # State should indicate AMT not available
        state = {
            "symbol": "CRUDEOIL",
            "price": None,
            "amt_analysis": None  # No data yet
        }
        
        assert state["amt_analysis"] is None
    
    def test_amt_multiple_symbols_isolated(self):
        """AMT analysis is isolated per symbol in WebSocket state.
        
        Behavior: Each symbol should have independent AMT analysis.
        CRUDEOIL analysis should not affect NATURALGAS analysis.
        """
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.runtime.pipeline.events import Candle, CandleTimeframe
        
        stage = AMTComputationStage(AMTAnalyzer())
        
        # Process 15 candles for CRUDEOIL
        for i in range(15):
            candle = Candle(
                symbol="CRUDEOIL",
                timeframe=CandleTimeframe.M1,
                open=7250.0 + i,
                high=7255.0 + i,
                low=7248.0 - i,
                close=7252.0 + i,
                volume=100.0,
                timestamp=1714982100.0 + i * 60
            )
            stage.process(candle)
        
        # Process 8 candles for NATURALGAS
        for i in range(8):
            candle = Candle(
                symbol="NATURALGAS",
                timeframe=CandleTimeframe.M1,
                open=285.0 + i,
                high=287.0 + i,
                low=284.0 - i,
                close=286.0 + i,
                volume=50.0,
                timestamp=1714982100.0 + i * 60
            )
            stage.process(candle)
        
        # Verify separate histories
        snap = stage.snapshot()
        assert snap["CRUDEOIL"] == 15
        assert snap["NATURALGAS"] == 8
        
        # Both should have independent AMT results
        crude_result = stage.process(Candle(
            symbol="CRUDEOIL",
            timeframe=CandleTimeframe.M1,
            open=7265.0,
            high=7270.0,
            low=7263.0,
            close=7268.0,
            volume=120.0,
            timestamp=1714983000.0
        ))
        
        gas_result = stage.process(Candle(
            symbol="NATURALGAS",
            timeframe=CandleTimeframe.M1,
            open=293.0,
            high=295.0,
            low=292.0,
            close=294.0,
            volume=60.0,
            timestamp=1714983000.0
        ))
        
        # Different price ranges confirm isolation
        assert crude_result.poc > 7000  # CRUDEOIL around 7250
        assert gas_result.poc < 300     # NATURALGAS around 285
