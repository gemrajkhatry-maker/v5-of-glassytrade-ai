"""
Example usage of the institutional-grade trading platform.
"""

import asyncio
from decimal import Decimal

from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.domain.order.models import OrderSide, OrderType
from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper
from brokersv2.infrastructure.dhan_adapter.client import DhanConfig
from brokersv2.infrastructure.dhan_adapter.adapter import DhanBrokerAdapter
from brokersv2.infrastructure.rate_limiter.token_bucket import RateLimiter
from brokersv2.risk.gateway import RiskGateway
from brokersv2.events.bus import EventBus
from brokersv2.oms.order_manager import OrderManager


async def main():
    """Example trading workflow."""
    
    # 1. Create instrument mapper
    mapper = InstrumentMapper()
    
    # 2. Register instruments (in production, load from CSV/database)
    instrument = CanonicalInstrument.create_equity("NSE", "RELIANCE")
    mapper.register(
        internal_uid=instrument.internal_uid,
        symbol="RELIANCE",
        exchange="NSE",
        security_id="12345",
        exchange_segment="NSE_EQ",
    )
    
    # 3. Create components
    rate_limiter = RateLimiter()
    event_bus = EventBus()
    risk = RiskGateway()
    
    # 4. Create broker adapter (requires credentials)
    # config = DhanConfig(client_id="...", access_token="...")
    # broker = DhanBrokerAdapter(config, mapper, rate_limiter)
    
    # 5. Create OMS
    # oms = OrderManager(broker, risk, event_bus)
    
    # 6. Place order
    # order = await oms.place_order(
    #     instrument=instrument,
    #     quantity=Decimal("10"),
    #     side=OrderSide.BUY,
    #     order_type=OrderType.MARKET,
    # )
    
    print("Platform initialized successfully!")
    print(f"Instrument: {instrument.canonical_symbol}")
    print(f"Mapper has {len(mapper._security_id_to_canonical)} instruments registered")


if __name__ == "__main__":
    asyncio.run(main())