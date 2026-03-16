import asyncio
import os
from dotenv import load_dotenv

from brokers.gateway import BrokerGateway
from brokers.broker.entities import Instrument
from brokers.broker.types import Exchange
from brokers.broker.dhan.infrastructure.symbol_mapper import DhanSymbolMapper

load_dotenv(dotenv_path='.env')

async def main():
    print("Initializing DhanSymbolMapper...")
    mapper = DhanSymbolMapper()
    await mapper.refresh_cache()
    
    # Try getting NIFTY 50 first as a basic test
    nifty_symbol = "NIFTY 50"
    print(f"\nLooking up instrument: {nifty_symbol}")
    nifty_inst = await mapper.get_instrument("13") # 13 is NIFTY 50 security ID on NSE
    
    if nifty_inst:
        print(f"Found: {nifty_inst.symbol} ({nifty_inst.exchange_segment})")
    else:
        print("Could not find NIFTY 50")
        return

    print("\nInitializing BrokerGateway...")
    try:
        gateway = BrokerGateway.dhan()
        print("BrokerGateway initialized.")
        
        print("\nFetching quote...")
        quote = gateway.get_quote(instrument=nifty_inst)
        print(f"Quote received: {quote}")
        print("\n✅ Broker connection verified!")
    except Exception as e:
        print(f"\n❌ Broker connection test failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
