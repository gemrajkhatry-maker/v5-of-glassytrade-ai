import asyncio
import logging
import threading
import time

from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

logging.basicConfig(level=logging.INFO)

class DummyDepth:
    def __init__(self, symbol, side, levels):
        self.symbol = symbol
        self.side = side
        self.levels = levels

class DummyLevel:
    def __init__(self, price, qty):
        self.price = price
        self.quantity = qty

class MockBrokerStream:
    def __init__(self, packets):
        self.packets = packets
        self.idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.idx >= len(self.packets):
            # Hang forever to simulate open connection
            await asyncio.sleep(100)
            raise StopAsyncIteration
        pkt = self.packets[self.idx]
        self.idx += 1
        await asyncio.sleep(0.1) # Simulate network delay
        return pkt

    async def aclose(self):
        pass

class MockBroker:
    def stream_full(self, symbols):
        # Emit a full packet (5 levels natively)
        packets = [
            {
                "symbol": "NIFTY",
                "timestamp": __import__("datetime").datetime.now(),
                "ltp": 25000.0,
                "volume": 100,
                "total_buy_qty": 50,
                "total_sell_qty": 50,
                "oi": 1000,
                "depth_bids": [{"price": 24999.0, "qty": 10}], # 1 level
                "depth_asks": [{"price": 25001.0, "qty": 10}],
            },
            {
                "symbol": "NIFTY",
                "timestamp": __import__("datetime").datetime.now(),
                "ltp": 25005.0,
                "volume": 200,
                "total_buy_qty": 100,
                "total_sell_qty": 100,
                "oi": 1000,
            }
        ]
        return MockBrokerStream(packets)

    def stream_depth_20(self, symbols):
        # Emit a depth packet with 20 levels
        levels_bid = [DummyLevel(25000 - i, 100 + i) for i in range(20)]
        levels_ask = [DummyLevel(25000 + i, 100 + i) for i in range(20)]
        packets = [
            DummyDepth("NIFTY", "bid", levels_bid),
            DummyDepth("NIFTY", "ask", levels_ask)
        ]
        return MockBrokerStream(packets)

def test_sanity():
    print("--- STARTING QUANT QA SANITY TEST ---")
    broker = MockBroker()
    feed = MultiplexedMarketFeed(broker)
    
    # 1. Subscribe
    feed.set_symbols(["NIFTY"])
    
    # Wait for packets to process
    time.sleep(1.0)
    
    print("--- READING TICKS ---")
    q = feed._queues.get("NIFTY")
    if not q:
        print("FAIL: No queue for NIFTY")
        return
        
    ticks = []
    while not q.empty():
        ticks.append(q.get())
        
    print(f"Captured {len(ticks)} ticks.")
    for i, tick in enumerate(ticks):
        print(f"\nTick {i+1}: LTP={tick.price} Vol={tick.volume}")
        if tick.depth:
            bids = tick.depth.get("bids", [])
            asks = tick.depth.get("asks", [])
            print(f"  Bids: {len(bids)} levels (Best: {bids[0]['price'] if bids else 'None'})")
            print(f"  Asks: {len(asks)} levels (Best: {asks[0]['price'] if asks else 'None'})")
            if len(bids) == 20:
                print("  SUCCESS: 20 levels merged successfully!")
            elif len(bids) > 0 and len(bids) < 20:
                print(f"  WARNING: Only {len(bids)} levels detected (likely from stream_full).")
            elif len(bids) == 0 and len(asks) == 0:
                print("  WARNING: Depth is empty.")
        else:
            print("  WARNING: No depth attached to tick.")
            
    feed.close()
    print("\n--- QA SANITY TEST COMPLETE ---")

if __name__ == "__main__":
    test_sanity()
