"""
Tests for Historical Replay Engine.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock
from brokersv2.replay.historical_replay import HistoricalReplayEngine
from brokersv2.replay.types import ReplayEvent, ReplayConfig


class TestReplayConfig:
    """Test replay configuration."""
    
    def test_valid_config(self):
        """Should validate correct config."""
        config = ReplayConfig(
            speed=1.0,
            from_date="2026-05-01",
            to_date="2026-05-07",
            timeframe="5m",
            symbols=["RELIANCE"],
        )
        
        assert config.is_valid is True
    
    def test_invalid_config_missing_dates(self):
        """Should reject config without dates."""
        config = ReplayConfig(symbols=["RELIANCE"])
        
        assert config.is_valid is False
    
    def test_invalid_config_zero_speed(self):
        """Should reject zero speed."""
        config = ReplayConfig(
            speed=0.0,
            from_date="2026-05-01",
            to_date="2026-05-07",
            timeframe="5m",
            symbols=["RELIANCE"],
        )
        
        assert config.is_valid is False


class TestHistoricalReplayEngine:
    """Test replay engine."""
    
    @pytest.mark.asyncio
    async def test_replay_single_symbol(self):
        """Should replay candles for single symbol."""
        mock_router = Mock()
        mock_router.get_candles = AsyncMock(return_value=[
            {"timestamp": datetime(2026, 5, 1, 9, 15), "open": 100, "close": 101},
            {"timestamp": datetime(2026, 5, 1, 9, 20), "open": 101, "close": 102},
        ])
        
        engine = HistoricalReplayEngine(
            historical_router=mock_router,
            symbols=["RELIANCE"],
            timeframe="5m",
            from_date="2026-05-01",
            to_date="2026-05-02",
            speed=100.0,  # Fast for testing
        )
        
        events = []
        async for event in engine.replay():
            events.append(event)
        
        assert len(events) == 2
        assert events[0].symbol == "RELIANCE"
        assert events[0].candle["open"] == 100
    
    @pytest.mark.asyncio
    async def test_replay_multi_symbol(self):
        """Should merge and sort candles from multiple symbols."""
        mock_router = Mock()
        
        def mock_get_candles(instrument, **kwargs):
            if instrument == "RELIANCE":
                return [
                    {"timestamp": datetime(2026, 5, 1, 9, 15), "open": 100},
                ]
            elif instrument == "TCS":
                return [
                    {"timestamp": datetime(2026, 5, 1, 9, 16), "open": 3500},
                ]
            return []
        
        mock_router.get_candles = AsyncMock(side_effect=mock_get_candles)
        
        engine = HistoricalReplayEngine(
            historical_router=mock_router,
            symbols=["RELIANCE", "TCS"],
            timeframe="5m",
            from_date="2026-05-01",
            to_date="2026-05-02",
            speed=100.0,
        )
        
        events = []
        async for event in engine.replay():
            events.append(event)
        
        assert len(events) == 2
        # Should be sorted by timestamp
        assert events[0].symbol == "RELIANCE"
        assert events[1].symbol == "TCS"
    
    @pytest.mark.asyncio
    async def test_pause_resume(self):
        """Should support pause and resume."""
        mock_router = Mock()
        mock_router.get_candles = AsyncMock(return_value=[
            {"timestamp": datetime(2026, 5, 1, 9, 15), "open": 100},
            {"timestamp": datetime(2026, 5, 1, 9, 20), "open": 101},
            {"timestamp": datetime(2026, 5, 1, 9, 25), "open": 102},
        ])
        
        engine = HistoricalReplayEngine(
            historical_router=mock_router,
            symbols=["RELIANCE"],
            timeframe="5m",
            from_date="2026-05-01",
            to_date="2026-05-02",
            speed=100.0,
        )
        
        events = []
        pause_triggered = False
        
        async def collect_events():
            nonlocal pause_triggered
            async for event in engine.replay():
                events.append(event)
                if len(events) == 1 and not pause_triggered:
                    pause_triggered = True
                    await engine.pause()
                    await asyncio.sleep(0.1)
                    await engine.resume()
        
        await asyncio.wait_for(collect_events(), timeout=2.0)
        
        assert len(events) == 3
    
    @pytest.mark.asyncio
    async def test_stop(self):
        """Should support stopping replay."""
        mock_router = Mock()
        mock_router.get_candles = AsyncMock(return_value=[
            {"timestamp": datetime(2026, 5, 1, 9, i), "open": 100 + i}
            for i in range(15, 30)
        ])
        
        engine = HistoricalReplayEngine(
            historical_router=mock_router,
            symbols=["RELIANCE"],
            timeframe="5m",
            from_date="2026-05-01",
            to_date="2026-05-02",
            speed=100.0,
        )
        
        events = []
        async for event in engine.replay():
            events.append(event)
            if len(events) == 2:
                await engine.stop()
        
        # Should stop early
        assert len(events) <= 3
    
    @pytest.mark.asyncio
    async def test_empty_candles(self):
        """Should handle empty candle data gracefully."""
        mock_router = Mock()
        mock_router.get_candles = AsyncMock(return_value=[])
        
        engine = HistoricalReplayEngine(
            historical_router=mock_router,
            symbols=["RELIANCE"],
            timeframe="5m",
            from_date="2026-05-01",
            to_date="2026-05-02",
            speed=100.0,
        )
        
        events = []
        async for event in engine.replay():
            events.append(event)
        
        assert len(events) == 0
    
    @pytest.mark.asyncio
    async def test_sequence_tracking(self):
        """Should track sequence numbers."""
        mock_router = Mock()
        mock_router.get_candles = AsyncMock(return_value=[
            {"timestamp": datetime(2026, 5, 1, 9, 15), "open": 100},
            {"timestamp": datetime(2026, 5, 1, 9, 20), "open": 101},
        ])
        
        engine = HistoricalReplayEngine(
            historical_router=mock_router,
            symbols=["RELIANCE"],
            timeframe="5m",
            from_date="2026-05-01",
            to_date="2026-05-02",
            speed=100.0,
        )
        
        async for _ in engine.replay():
            pass
        
        assert engine.sequence == 2
    
    def test_speed_minimum(self):
        """Should enforce minimum speed of 0.1x."""
        mock_router = Mock()
        
        engine = HistoricalReplayEngine(
            historical_router=mock_router,
            symbols=["RELIANCE"],
            timeframe="5m",
            from_date="2026-05-01",
            to_date="2026-05-02",
            speed=0.01,  # Below minimum
        )
        
        assert engine._speed == 0.1
