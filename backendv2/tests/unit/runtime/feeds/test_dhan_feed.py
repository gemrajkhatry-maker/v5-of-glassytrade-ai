"""Unit tests for DhanFeedSource - live tick streaming from broker.

These tests verify that DhanFeedSource properly wraps the DhanAdapter
and yields normalized Tick objects for the pipeline.

TDD Status: RED→GREEN cycle in progress
"""
import pytest
from unittest.mock import Mock
import time
import threading


class TestDhanFeedSource:
    """Test DhanFeedSource wraps broker adapter correctly."""
    
    def test_dhan_feed_source_yields_ticks(self):
        """DhanFeedSource yields normalized ticks from adapter.
        
        Behavior: When DhanFeedSource.stream() is called, it should:
        1. Call adapter.get_next_tick() repeatedly
        2. Convert raw tick dict to normalized Tick object
        3. Yield Tick with symbol, price, volume, timestamp
        
        This enables live market data to flow into the pipeline.
        """
        from app.runtime.feeds.dhan_feed import DhanFeedSource
        from app.runtime.pipeline.events import Tick
        
        # Mock DhanAdapter
        mock_adapter = Mock()
        mock_adapter.get_next_tick.return_value = {
            "symbol": "CRUDEOIL",
            "price": 7253.0,
            "volume": 100,
            "timestamp": 1714982100.0
        }
        
        feed = DhanFeedSource(mock_adapter)
        feed.start()
        
        # Get first tick
        tick = next(feed.stream())
        
        # Verify tick is normalized
        assert tick.symbol == "CRUDEOIL"
        assert tick.price == 7253.0
        assert tick.volume == 100
        # Timestamp is in nanoseconds (Tick spec)
        assert tick.timestamp == 1714982100.0 * 1_000_000_000
        
        feed.stop()
    
    def test_dhan_feed_skips_empty_ticks(self):
        """Feed skips None/empty ticks without yielding.
        
        Behavior: When adapter returns None or invalid data,
        feed should skip and continue waiting for valid ticks.
        This prevents pipeline crashes from broker disconnections.
        """
        from app.runtime.feeds.dhan_feed import DhanFeedSource
        
        mock_adapter = Mock()
        # Return None twice, then a valid tick
        mock_adapter.get_next_tick.side_effect = [
            None,  # First call: no data
            None,  # Second call: still no data
            {
                "symbol": "CRUDEOIL",
                "price": 7253.0,
                "volume": 100,
                "timestamp": 1714982100.0
            }  # Third call: valid tick
        ]
        
        feed = DhanFeedSource(mock_adapter)
        feed.start()
        
        ticks = []
        def collect_ticks():
            for tick in feed.stream():
                ticks.append(tick)
                if len(ticks) >= 1:
                    break  # Stop after first valid tick
        
        thread = threading.Thread(target=collect_ticks)
        thread.start()
        time.sleep(0.5)  # Wait for ticks to process
        feed.stop()
        thread.join(timeout=1.0)
        
        # Should only have the valid tick, not the None values
        assert len(ticks) == 1
        assert ticks[0].symbol == "CRUDEOIL"
        assert mock_adapter.get_next_tick.call_count == 3
    
    def test_dhan_feed_stops_cleanly(self):
        """Feed stops cleanly when stop() is called.
        
        Behavior: When stop() is called, the stream generator should
        exit gracefully without raising exceptions.
        """
        from app.runtime.feeds.dhan_feed import DhanFeedSource
        
        mock_adapter = Mock()
        mock_adapter.get_next_tick.return_value = {
            "symbol": "CRUDEOIL",
            "price": 7253.0,
            "volume": 100,
            "timestamp": 1714982100.0
        }
        
        feed = DhanFeedSource(mock_adapter)
        feed.start()
        
        # Start consuming ticks in background
        tick_count = 0
        def consume():
            nonlocal tick_count
            for tick in feed.stream():
                tick_count += 1
                time.sleep(0.1)  # Simulate processing
        
        thread = threading.Thread(target=consume)
        thread.start()
        
        # Let it run briefly
        time.sleep(0.3)
        
        # Stop should exit cleanly
        feed.stop()
        thread.join(timeout=1.0)
        
        # Should not hang or raise exception
        assert not thread.is_alive()
        assert tick_count > 0
    
    def test_dhan_feed_invalid_price_skipped(self):
        """Feed skips ticks with invalid price (None, 0, negative).
        
        Behavior: Ticks with price <= 0 should be skipped to prevent
        pipeline errors from corrupt broker data.
        """
        from app.runtime.feeds.dhan_feed import DhanFeedSource
        
        mock_adapter = Mock()
        # Mix of invalid and valid ticks
        mock_adapter.get_next_tick.side_effect = [
            {"symbol": "CRUDEOIL", "price": 0, "volume": 100, "timestamp": 1714982100.0},
            {"symbol": "CRUDEOIL", "price": -5.0, "volume": 100, "timestamp": 1714982101.0},
            {"symbol": "CRUDEOIL", "price": None, "volume": 100, "timestamp": 1714982102.0},
            {"symbol": "CRUDEOIL", "price": 7253.0, "volume": 100, "timestamp": 1714982103.0},
        ]
        
        feed = DhanFeedSource(mock_adapter)
        feed.start()
        
        ticks = []
        def collect():
            for tick in feed.stream():
                ticks.append(tick)
                if len(ticks) >= 1:
                    break
        
        thread = threading.Thread(target=collect)
        thread.start()
        time.sleep(0.5)
        feed.stop()
        thread.join(timeout=1.0)
        
        # Only the valid tick should be yielded
        assert len(ticks) == 1
        assert ticks[0].price == 7253.0
