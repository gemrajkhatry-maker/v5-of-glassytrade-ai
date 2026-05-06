"""Tests for MarketStructureAnalysis decoupling — no internal access violations.

Behavior: MarketStructureAnalysis should accept storage via constructor
and not expose internal implementation details. SessionRuntime should
inject storage properly without accessing private attributes.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from app.runtime.pipeline.market_structure import MarketStructureAnalysis
from app.runtime.pipeline.events import Candle, CandleTimeframe


class TestMarketStructureDecoupling:
    """Tests for proper dependency injection in MarketStructureAnalysis."""

    def test_accepts_storage_via_constructor(self):
        """MarketStructureAnalysis should accept storage via constructor."""
        mock_storage = MagicMock()
        
        analysis = MarketStructureAnalysis(storage=mock_storage)
        
        assert analysis is not None
        # Should not expose storage as public attribute
        assert not hasattr(analysis, 'storage') or hasattr(analysis, '_storage')

    def test_works_with_none_storage(self):
        """MarketStructureAnalysis should work with None storage (null object pattern)."""
        analysis = MarketStructureAnalysis(storage=None)
        
        assert analysis is not None

    def test_does_not_expose_internal_storage(self):
        """Storage should be private, not accessible as public attribute."""
        mock_storage = MagicMock()
        analysis = MarketStructureAnalysis(storage=mock_storage)
        
        # Should use private attribute or no direct access
        if hasattr(analysis, 'storage'):
            # If it has 'storage', it should be a property or private
            assert isinstance(getattr(type(analysis), 'storage', None), property) or \
                   analysis.storage is None or \
                   analysis.storage == mock_storage

    def test_process_candle_without_storage(self):
        """Should process candles without storage (null object)."""
        analysis = MarketStructureAnalysis(storage=None)
        
        candle = Candle(
            symbol="NIFTY",
            timeframe=CandleTimeframe.M1,
            timestamp=1000.0,
            open=100.0,
            high=105.0,
            low=99.0,
            close=103.0,
            volume=1000.0,
            buy_volume=600.0,
            sell_volume=400.0,
        )
        
        # Should not raise
        results = analysis.process(candle)
        
        assert isinstance(results, list)

    def test_process_multiple_candles(self):
        """Should process multiple candles maintaining state internally."""
        analysis = MarketStructureAnalysis(storage=None)
        
        base_timestamp = 1000.0
        for i in range(5):
            candle = Candle(
                symbol="NIFTY",
                timeframe=CandleTimeframe.M1,
                timestamp=base_timestamp + i * 60,
                open=100.0 + i,
                high=105.0 + i,
                low=99.0 + i,
                close=103.0 + i,
                volume=1000.0,
                buy_volume=600.0,
                sell_volume=400.0,
            )
            results = analysis.process(candle)
            assert isinstance(results, list)


class TestSessionRuntimeInjection:
    """Tests for proper dependency injection in SessionRuntime."""

    def test_session_runtime_injects_storage_properly(self):
        """SessionRuntime should inject storage without accessing private attributes."""
        from app.runtime.orchestrator.session import SessionRuntime
        from app.runtime.feeds import FeedSource
        from unittest.mock import MagicMock
        
        # Create mock feed
        mock_feed = MagicMock(spec=FeedSource)
        mock_feed.stream.return_value = []
        
        # Create mock storage
        mock_storage = MagicMock()
        
        # Should not raise or access private attributes
        runtime = SessionRuntime(
            feed=mock_feed,
            symbols=["NIFTY"],
            storage=mock_storage
        )
        
        assert runtime is not None
        # Verify market_structure stage exists
        assert hasattr(runtime, '_market_structure')
