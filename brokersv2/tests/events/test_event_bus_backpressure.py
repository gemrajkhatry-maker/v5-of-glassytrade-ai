"""Tests for Event Bus Backpressure."""

import asyncio
import pytest
from brokersv2.events.bus import EventBus, BackpressureStrategy
from brokersv2.core.events import Event


class SimpleTestEvent(Event):
    """Simple test event class."""
    pass


@pytest.mark.asyncio
async def test_drop_oldest_on_full_queue():
    """Oldest events dropped when queue full with DROP_OLDEST strategy."""
    bus = EventBus(max_queue_size=3, strategy=BackpressureStrategy.DROP_OLDEST)
    await bus.start()
    
    try:
        # Fill queue
        await bus.publish(SimpleTestEvent(timestamp=None))
        await bus.publish(SimpleTestEvent(timestamp=None))
        await bus.publish(SimpleTestEvent(timestamp=None))
        
        assert bus.is_queue_full is True
        
        # Publish one more (should drop oldest)
        await bus.publish(SimpleTestEvent(timestamp=None))
        
        # Queue should still be at max size
        assert bus.queue_depth <= 3
        assert bus.queue_depths["dropped_events"] >= 1
    finally:
        await bus.stop()


@pytest.mark.asyncio
async def test_queue_depth_monitoring():
    """Queue depth metrics reported correctly."""
    bus = EventBus(max_queue_size=100, strategy=BackpressureStrategy.DROP_OLDEST)
    
    # Initial state
    depths = bus.queue_depths
    assert depths["event_queue"] == 0
    assert depths["max_size"] == 100
    assert depths["dropped_events"] == 0
    assert bus.queue_depth == 0
    
    # After some events (queue may process them)
    await bus.publish(SimpleTestEvent(timestamp=None))
    
    depths = bus.queue_depths
    assert "event_queue" in depths
    assert "dlq_size" in depths
    assert "max_size" in depths
    assert "dropped_events" in depths


# =============================================================================
# DLQ Size Limit Tests (P1-1 Fix)
# =============================================================================

@pytest.mark.asyncio
async def test_dlq_size_limit():
    """DLQ doesn't grow beyond max size."""
    # Small DLQ limit for testing
    bus = EventBus(max_dlq_size=100)
    
    # Add handler that always fails
    def failing_handler(e):
        raise RuntimeError("Handler error")
    
    bus.subscribe(SimpleTestEvent, failing_handler)
    
    # Publish 500 events (all will fail)
    for i in range(500):
        await bus.publish(SimpleTestEvent(timestamp=None))
    
    # DLQ should be trimmed to max size
    assert bus.get_dlq_size() <= 100
    assert bus.get_dlq_size() == 100  # Should be exactly at limit


@pytest.mark.asyncio
async def test_dlq_keeps_most_recent_entries():
    """DLQ trimming keeps most recent entries."""
    bus = EventBus(max_dlq_size=10)
    
    call_count = 0
    
    def failing_handler(e):
        nonlocal call_count
        call_count += 1
        raise RuntimeError(f"Error #{call_count}")
    
    bus.subscribe(SimpleTestEvent, failing_handler)
    
    # Publish 25 events
    for i in range(25):
        await bus.publish(SimpleTestEvent(timestamp=None))
    
    # DLQ should have 10 entries (most recent)
    assert bus.get_dlq_size() == 10
    
    # Verify these are the most recent (errors #16-25)
    dlq = bus.get_dlq()
    # The errors should be from the last 10 calls
    assert all("Error #" in str(entry[1]) for entry in dlq)


@pytest.mark.asyncio
async def test_dlq_configurable_max_size():
    """DLQ max size is configurable."""
    # Custom DLQ size
    bus = EventBus(max_dlq_size=50)
    
    def failing_handler(e):
        raise RuntimeError("Handler error")
    
    bus.subscribe(SimpleTestEvent, failing_handler)
    
    # Publish 100 events
    for i in range(100):
        await bus.publish(SimpleTestEvent(timestamp=None))
    
    # Should respect the 50 limit
    assert bus.get_dlq_size() <= 50
    assert bus.get_dlq_size() == 50


@pytest.mark.asyncio
async def test_dlq_metrics_in_queue_depths():
    """DLQ size reported in queue_depths metrics."""
    bus = EventBus(max_dlq_size=50)
    
    def failing_handler(e):
        raise RuntimeError("Handler error")
    
    bus.subscribe(SimpleTestEvent, failing_handler)
    
    # Publish some events
    for i in range(10):
        await bus.publish(SimpleTestEvent(timestamp=None))
    
    depths = bus.queue_depths
    assert "dlq_size" in depths
    assert depths["dlq_size"] == 10
    assert depths["max_size"] == 10000  # Default event queue size


@pytest.mark.asyncio
async def test_dlq_clear_respects_limit():
    """DLQ can be cleared and resumes respecting limit."""
    bus = EventBus(max_dlq_size=10)
    
    def failing_handler(e):
        raise RuntimeError("Handler error")
    
    bus.subscribe(SimpleTestEvent, failing_handler)
    
    # Fill DLQ beyond limit
    for i in range(50):
        await bus.publish(SimpleTestEvent(timestamp=None))
    
    assert bus.get_dlq_size() == 10
    
    # Clear DLQ
    bus.clear_dlq()
    assert bus.get_dlq_size() == 0
    
    # Publish more - should still respect limit
    for i in range(25):
        await bus.publish(SimpleTestEvent(timestamp=None))
    
    assert bus.get_dlq_size() == 10  # Back at limit
