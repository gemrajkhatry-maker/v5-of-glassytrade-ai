import asyncio
import logging
from datetime import datetime, timezone

from app.domain.ports.event_bus import EventBusPort
from app.domain.trading.events import TickReceived
from app.domain.trading.models.value_objects import Tick
from app.application.services.trading_session import TradingSessionService
from app.domain.trading.event_store import EventBus

logging.basicConfig(level=logging.INFO)

def test_queue():
    bus = EventBus()
    
    # Mock dependencies
    class MockBroker: pass
    class MockGenAI: pass
    
    svc = TradingSessionService(
        event_bus=bus,
        broker=MockBroker(),
        gen_ai_service=MockGenAI()
    )
    
    # Simulate first tick (establishes candle time)
    t1 = Tick(symbol="NIFTY", price=100.0, volume=1, time="2024-01-01T10:00:00Z")
    bus.publish(TickReceived(symbol="NIFTY", tick=t1, data=[t1], order_book=None))
    
    # Simulate first tick for another symbol
    t2 = Tick(symbol="BANKNIFTY", price=200.0, volume=1, time="2024-01-01T10:00:00Z")
    bus.publish(TickReceived(symbol="BANKNIFTY", tick=t2, data=[t2], order_book=None))

    # Send new candle ticks simultaneously to trigger reasoning
    print("Triggering new candle for NIFTY...")
    t1_new = Tick(symbol="NIFTY", price=101.0, volume=1, time="2024-01-01T10:05:00Z")
    bus.publish(TickReceived(symbol="NIFTY", tick=t1_new, data=[t1, t1_new], order_book=None))
    
    print("Triggering new candle for BANKNIFTY...")
    t2_new = Tick(symbol="BANKNIFTY", price=201.0, volume=1, time="2024-01-01T10:05:00Z")
    bus.publish(TickReceived(symbol="BANKNIFTY", tick=t2_new, data=[t2, t2_new], order_book=None))
    
    print("Check backend logs for queue processing.")

if __name__ == "__main__":
    test_queue()
