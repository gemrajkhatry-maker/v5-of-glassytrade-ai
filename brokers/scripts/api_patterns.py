"""
Example script showing brokers package API usage patterns.

This demonstrates the API structure without requiring live credentials.
For actual live calls, set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN env vars.
"""

import asyncio
from datetime import datetime, timedelta

from brokers.broker.dhan.application.broker import DhanBroker
from brokers.broker.dhan.application.config import DhanConfig
from brokers.broker.entities import Instrument
from brokers.broker.types import Exchange


def show_api_patterns():
    """Show available API patterns."""
    print("=" * 70)
    print("DHAN BROKER API PATTERNS (brokers package)")
    print("=" * 70)
    
    print("""
1. HISTORICAL DATA
-----------------
# Create broker
broker = DhanBroker.create(client_id="...", access_token="...")

# Get historical data
df = broker.get_historical(
    instrument=Instrument(symbol="RELIANCE", exchange=Exchange.NSE),
    from_date=datetime(2024, 1, 1),
    to_date=datetime(2024, 1, 31),
    interval="1d",  # "1d", "1", "5", "15", "25", "60"
    include_oi=True,  # Include open interest
)

# Bulk historical
result = broker.bulk_historical(
    symbols=["RELIANCE", "TCS", "INFY"],
    from_date=datetime(2024, 1, 1),
    to_date=datetime(2024, 1, 31),
    exchange=Exchange.NSE,
    interval="1d",
)

2. OPTION CHAIN
---------------
# Get option chain
chain = broker.get_option_chain(
    underlying="NIFTY",
    exchange=Exchange.NSE,
    expiry_index=0,  # 0=current week, 1=near month, 2=far month
)

# Get expiry list
expiries = broker.get_expiry_list(
    underlying="NIFTY",
    exchange=Exchange.NSE,
)

# Format option symbol
symbol = DhanBroker.format_option_symbol(
    underlying="NIFTY",
    expiry=datetime(2024, 1, 25),
    strike=21500,
    option_type="CE",  # "CE" or "PE"
)

3. MARKET DATA
--------------
# Quote
quote = broker.get_quote(instrument)

# Batch quotes
quotes = broker.get_quotes_batch([inst1, inst2, inst3])

# LTP
ltp = broker.get_ltp(instrument)

# Lot size
lot_size = broker.get_lot_size("RELIANCE", Exchange.NSE)

4. STREAMING
------------
# Stream ticks
async for tick in broker.stream_ticker([instrument]):
    print(tick.ltp)

# Stream quotes
async for quote in broker.stream_quotes([instrument]):
    print(quote.bid, quote.ask)

# Stream depth (20 levels)
async for depth in broker.stream_depth(instrument, depth_level=20):
    print(depth.bids, depth.asks)

5. ORDERS
---------
# Place order
order = Order(
    symbol="RELIANCE",
    exchange=Exchange.NSE,
    side="BUY",
    quantity=10,
    order_type="MARKET",
    product_type="INTRADAY",
    price=0,
    disclosed_quantity=0,
)
result = broker.place_order(order)

# Cancel order
broker.cancel_order(order_id="123456")

# Get order status
order = broker.get_order_status(order_id="123456")

# Orderbook
orders = broker.get_orderbook()

6. PORTFOLIO
------------
# Positions
positions = broker.get_positions()

# Trade history
trades = broker.get_trade_history_async(from_date, to_date)

# P&L
pnl = broker.get_pnl_async(from_date, to_date)
""")

    print("\nFor live API calls, run:")
    print("  DHAN_CLIENT_ID=your_id DHAN_ACCESS_TOKEN=your_token python scripts/live_api_demo.py")


if __name__ == "__main__":
    show_api_patterns()