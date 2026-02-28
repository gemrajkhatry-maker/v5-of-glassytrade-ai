import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv

from brokers.gateway import BrokerGateway
from brokers.broker.entities import Instrument
from brokers.broker.types import Exchange
from brokers.broker.dhan.infrastructure.symbol_mapper import DhanSymbolMapper

load_dotenv(dotenv_path='../.env')
load_dotenv(dotenv_path='.env')

async def test_connection():
    # The actual security ID for GIFTNIFTY is 5024
    security_id = "5024"
    print(f"=== Testing Broker Connection for Security ID {security_id} ===")
    
    mapper = DhanSymbolMapper()
    await mapper.refresh_cache()
    
    dhan_inst = await mapper.get_instrument(security_id)
    if not dhan_inst:
        print(f"Failed to find instrument with security_id {security_id}")
        return
        
    print(f"\nInstrument Found:")
    print(f"  Symbol           : {dhan_inst.symbol}")
    print(f"  Trading Symbol   : {dhan_inst.trading_symbol}")
    print(f"  Instrument Type  : {dhan_inst.instrument_type}")
    print(f"  Exchange Segment : {dhan_inst.exchange_segment.name if dhan_inst.exchange_segment else None}")
    
    try:
        gateway = BrokerGateway.dhan()
        print("\nSuccessfully initialized Dhan Broker Gateway.")
    except Exception as e:
        print(f"Failed to initialize Broker Gateway: {e}")
        return
        
    exchange = dhan_inst.exchange_segment.to_exchange() if dhan_inst.exchange_segment else Exchange.INDEX
    
    print(f"\n1. Testing get_quote() for {dhan_inst.trading_symbol} ({exchange.value}:{security_id})...")
    try:
        quote = gateway.get_quote(symbol=dhan_inst.trading_symbol, exchange=exchange, security_id=security_id)
        print(f"Quote Result: {quote}")
    except Exception as e:
        print(f"Failed to get quote: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
