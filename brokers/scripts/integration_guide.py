"""
Integration guide: Using brokers and brokersv2 together.

This shows how the new brokersv2 architecture can coexist with the existing brokers package.
"""

import asyncio
from datetime import datetime, timedelta

# Old brokers (existing production code)
from brokers.broker.dhan.application import DhanBroker
from brokers.broker.entities import Instrument
from brokers.broker.types import Exchange

# New brokersv2 (new architecture)
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper
from brokersv2.infrastructure.dhan_adapter.client import DhanConfig, DhanHttpClient
from brokersv2.infrastructure.rate_limiter.token_bucket import RateLimiter
from brokersv2.events.bus import EventBus


def compare_architectures():
    """Show comparison between old and new architectures."""
    print("=" * 70)
    print("ARCHITECTURE COMPARISON: brokers vs brokersv2")
    print("=" * 70)
    
    print("""
OLD (brokers) - Direct broker coupling:
---------------------------------------
# Directly uses broker-specific identifiers
instrument = Instrument(symbol="RELIANCE", exchange=Exchange.NSE)

# Uses raw security_id internally
df = broker.get_historical(instrument, from_date, to_date, interval="1d")

# Mixed concerns: market data, orders, portfolio all in one class
quote = broker.get_quote(instrument)
order = broker.place_order(order_req)
positions = broker.get_positions()


NEW (brokersv2) - Clean architecture:
------------------------------------
# Uses canonical instruments (broker-agnostic)
instrument = CanonicalInstrument.create_equity("NSE", "RELIANCE")

# O(1) mapper for broker translation
mapper = InstrumentMapper()
security_id = mapper.canonical_to_security_id(instrument)

# Separated concerns: each layer has single responsibility
# - Core domain: CanonicalInstrument, Order
# - Infrastructure: DhanHttpClient, InstrumentMapper  
# - Application: OrderManager, RiskGateway
# - Presentation: EventBus, WebSocketManager

# Broker-specific details are completely hidden
adapter = DhanBrokerAdapter(config, mapper, rate_limiter)
""")

    print("""
MIGRATION PATH:
--------------
1. Keep existing brokers code for production
2. New strategies use brokersv2 with clean separation
3. brokersv2's CanonicalInstrument format: "NSE:RELIANCE"
4. brokersv2's InstrumentMapper handles translation to security_id
5. EventBus publishes TickEvent, QuoteEvent from both sources
""")


async def hybrid_example():
    """Example showing both can coexist."""
    print("\n" + "=" * 70)
    print("HYBRID USAGE EXAMPLE")
    print("=" * 70)
    
    # Old way - direct broker call
    print("\n# Old way (brokers):")
    print("broker = DhanBroker.create(client_id='...', access_token='...')")
    print("quote = broker.get_quote(Instrument(symbol='RELIANCE', exchange=Exchange.NSE))")
    
    # New way - clean architecture
    print("\n# New way (brokersv2):")
    print("instrument = CanonicalInstrument.create_equity('NSE', 'RELIANCE')")
    print("mapper = InstrumentMapper()")
    print("bus = EventBus()")
    print("")
    print("# Subscribe to events from either source")
    print("bus.subscribe(QuoteEvent, async_handler)")
    
    # Both publish to the same event bus
    print("\n# Both can publish to same EventBus")
    print("# Old broker -> convert to CanonicalInstrument -> publish")
    print("# New broker -> direct publish")


if __name__ == "__main__":
    compare_architectures()
    asyncio.run(hybrid_example())