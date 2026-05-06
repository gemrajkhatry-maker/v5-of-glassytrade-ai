"""Unit tests for AMTComputationStage - computes AMT analysis on candles.

These tests verify that AMTComputationStage processes candles through
the AMTAnalyzer and returns AMTResult objects for WebSocket streaming.

TDD Status: RED→GREEN cycle in progress
"""
import pytest


class TestAMTComputationStage:
    """Test AMTComputationStage processes candles correctly."""
    
    def test_amt_stage_computes_result(self):
        """AMTComputationStage processes candle and returns AMTResult.
        
        Behavior: When stage.process() is called with a candle, it should:
        1. Accumulate candle in per-symbol history
        2. Run AMTAnalyzer on accumulated bars
        3. Return AMTResult with market state, POC, VAH, VAL, etc.
        
        This enables real-time AMT analysis for each symbol.
        """
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.runtime.pipeline.events import Candle, CandleTimeframe
        
        stage = AMTComputationStage(AMTAnalyzer())
        
        # Create test candle
        candle = Candle(
            symbol="CRUDEOIL",
            timeframe=CandleTimeframe.M1,
            open=7250.0,
            high=7255.0,
            low=7248.0,
            close=7253.0,
            volume=100.0,
            timestamp=1714982100.0
        )
        
        result = stage.process(candle)
        
        # Verify AMTResult structure exists
        assert result is not None
        assert hasattr(result, 'market_state')
        assert hasattr(result, 'poc')
        # First candle may have default values, but structure should exist
        assert isinstance(result.market_state, str)
    
    def test_amt_stage_maintains_history_per_symbol(self):
        """Stage maintains separate history for each symbol.
        
        Behavior: Candles for different symbols should be tracked
        independently. CRUDEOIL history should not mix with NATURALGAS.
        """
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.runtime.pipeline.events import Candle, CandleTimeframe
        
        stage = AMTComputationStage(AMTAnalyzer())
        
        # Process 3 candles for CRUDEOIL
        for i in range(3):
            candle = Candle(
                symbol="CRUDEOIL",
                timeframe=CandleTimeframe.M1,
                open=7250.0 + i,
                high=7255.0 + i,
                low=7248.0 + i,
                close=7253.0 + i,
                volume=100.0,
                timestamp=1714982100.0 + i * 60
            )
            stage.process(candle)
        
        # Process 2 candles for NATURALGAS
        for i in range(2):
            candle = Candle(
                symbol="NATURALGAS",
                timeframe=CandleTimeframe.M1,
                open=285.0 + i,
                high=287.0 + i,
                low=284.0 + i,
                close=286.0 + i,
                volume=50.0,
                timestamp=1714982100.0 + i * 60
            )
            stage.process(candle)
        
        # Verify separate histories
        snap = stage.snapshot()
        assert snap["CRUDEOIL"] == 3
        assert snap["NATURALGAS"] == 2
    
    def test_amt_stage_limits_history(self):
        """Stage limits history to max_history candles.
        
        Behavior: To prevent memory bloat, stage should only keep
        the last N candles (default 200). Older candles are discarded.
        """
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.runtime.pipeline.events import Candle, CandleTimeframe
        
        stage = AMTComputationStage(AMTAnalyzer(), max_history=5)
        
        # Process 10 candles
        for i in range(10):
            candle = Candle(
                symbol="CRUDEOIL",
                timeframe=CandleTimeframe.M1,
                open=7250.0 + i,
                high=7255.0 + i,
                low=7248.0 + i,
                close=7253.0 + i,
                volume=100.0,
                timestamp=1714982100.0 + i * 60
            )
            stage.process(candle)
        
        # Verify limited to 5
        snap = stage.snapshot()
        assert snap["CRUDEOIL"] == 5
    
    def test_amt_stage_returns_complete_result(self):
        """Stage returns AMTResult with all required fields populated.
        
        Behavior: After processing enough candles, AMTResult should
        have meaningful values for market state, profile levels, etc.
        """
        from app.runtime.pipeline.amt_computation import AMTComputationStage
        from app.domain.amt.service.amt_analyzer import AMTAnalyzer
        from app.runtime.pipeline.events import Candle, CandleTimeframe
        
        stage = AMTComputationStage(AMTAnalyzer())
        
        # Process 20 candles to build meaningful profile
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
            stage.process(candle)
        
        result = stage.process(Candle(
            symbol="CRUDEOIL",
            timeframe=CandleTimeframe.M1,
            open=7252.0,
            high=7258.0,
            low=7250.0,
            close=7256.0,
            volume=150.0,
            timestamp=1714983300.0
        ))
        
        # Verify key fields are populated
        assert result.market_state in ["BALANCED", "IMBALANCED"]
        assert result.poc > 0  # POC should be calculated
        assert result.value_area_high > 0
        assert result.value_area_low > 0
        assert result.value_area_high >= result.poc
        assert result.value_area_low <= result.poc
