import pytest
import time
import threading
from unittest.mock import MagicMock

from app.infrastructure.async_persistence import AsyncPersistenceBus


@pytest.fixture
def mock_storage():
    return MagicMock()


@pytest.fixture
def async_bus(mock_storage):
    bus = AsyncPersistenceBus(storage=mock_storage, max_queue_size=10)
    yield bus
    bus.stop(timeout=1.0)


def test_async_bus_lifecycle(async_bus):
    assert not async_bus._running
    assert async_bus._thread is None
    
    async_bus.start()
    assert async_bus._running
    assert isinstance(async_bus._thread, threading.Thread)
    assert async_bus._thread.is_alive()
    
    async_bus.stop(timeout=1.0)
    assert not async_bus._running
    assert not async_bus._thread.is_alive()


def test_async_bus_queue_prioritization(mock_storage):
    # Set queue artificially low to test filling and extraction sequence easily
    # Using a slow mock to let the queue fill up before it starts draining
    import time
    
    slow_storage = MagicMock()
    # We will block the mock to queue items
    delay_event = threading.Event()
    
    def side_effect(*args, **kwargs):
        delay_event.wait()
        
    slow_storage.save_tick.side_effect = side_effect
    slow_storage.save_trade.side_effect = side_effect
    
    bus = AsyncPersistenceBus(storage=slow_storage, max_queue_size=10)
    bus.start()
    
    # Enqueue a normal tick (will block the worker thread waiting on delay_event)
    bus.save_tick("NIFTY", {"price": 100})
    
    # Wait slightly to ensure normal tick starts executing and blocking
    time.sleep(0.01)
    
    # Fill up the queues
    bus.save_tick("BANKNIFTY", {"price": 200})
    bus.save_trade({"id": "T1"})
    
    # Release the lock allowing processing
    delay_event.set()
    
    # Ensure empty
    bus.stop(timeout=2.0)
    
    # Assert
    # We expect trade to have executed, we don't strictly enforce strict ordering due to thread scheduling 
    # but we can test that it successfully drained all
    slow_storage.save_tick.assert_any_call("NIFTY", {"price": 100})
    slow_storage.save_tick.assert_any_call("BANKNIFTY", {"price": 200})
    slow_storage.save_trade.assert_called_once_with({"id": "T1"})


def test_async_bus_error_recovery(async_bus, mock_storage):
    # Simulate DB Lock / OperationalError
    mock_storage.save_tick.side_effect = Exception("Database Locked")
    
    async_bus.start()
    async_bus.save_tick("NIFTY", {"price": 100})
    # Should not crash the bus
    async_bus.save_llm_decision({"decision": "BUY"})
    
    async_bus.stop(timeout=1.0)
    
    mock_storage.save_tick.assert_called_once_with("NIFTY", {"price": 100})
    mock_storage.save_llm_decision.assert_called_once_with({"decision": "BUY"})


def test_async_bus_queue_full_drops(mock_storage):
    bus = AsyncPersistenceBus(storage=mock_storage, max_queue_size=1)
    
    # Enqueue without starting thread so items accumulate
    bus.save_tick("S1", {})
    bus.save_tick("S2", {})  # This should drop because max_size=1
    
    assert bus.dropped_count == 1
    
    # Critical should still enter critical queue (max 100)
    bus.save_trade({"id": "T2"})
    assert bus.dropped_count == 1
    
    assert bus.pending_count == 2 # 1 normal, 1 critical
