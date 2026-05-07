#!/usr/bin/env python3
"""
Integration test: Historical data, options chain, and live streaming.
Verifies core broker functionality using project venv.
"""
import sys
import asyncio
from datetime import datetime, timedelta

# Ensure we're using project venv
print(f"Python: {sys.executable}")
print(f"Python version: {sys.version}")

sys.path.insert(0, '/Users/apple/Downloads/v5-of-glassytrade-ai')

from brokers.gateway import BrokerGateway
from brokers.broker.types import Exchange


def test_historical_data():
    """Test historical data fetching."""
    print("\n=== Testing Historical Data ===")
    
    gateway = BrokerGateway.paper()
    
    # Test historical data request
    to_date = datetime.now()
    from_date = to_date - timedelta(days=5)
    
    try:
        historical = gateway.get_historical(
            "RELIANCE",
            Exchange.NSE,
            from_date=from_date,
            to_date=to_date,
            interval="1d"
        )
        
        print(f"✓ Historical data request succeeded")
        print(f"  Type: {type(historical)}")
        if hasattr(historical, 'empty'):
            # It's a DataFrame
            print(f"  Records: {len(historical) if not historical.empty else 0}")
        elif historical:
            print(f"  Records: {len(historical) if hasattr(historical, '__len__') else 'N/A'}")
        
        print("✅ Historical data test PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Historical data test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        gateway.close()


def test_options_chain():
    """Test options chain retrieval."""
    print("\n=== Testing Options Chain ===")
    
    gateway = BrokerGateway.paper()
    
    try:
        # Get option chain
        chain = gateway.get_option_chain("NIFTY", Exchange.NFO)
        
        print(f"✓ Option chain retrieved")
        print(f"  Underlying: {chain.underlying.symbol}")
        print(f"  Strikes: {len(chain.strikes) if hasattr(chain, 'strikes') else 'N/A'}")
        
        # Get expiry list
        expiries = gateway.get_expiries("NIFTY", Exchange.NFO)
        print(f"✓ Expiry list retrieved")
        print(f"  Expiries: {len(expiries)} dates")
        if expiries:
            print(f"  First expiry: {expiries[0]}")
        
        print("✅ Options chain test PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Options chain test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        gateway.close()


async def test_live_streaming():
    """Test live streaming subscription."""
    print("\n=== Testing Live Streaming ===")
    
    gateway = BrokerGateway.paper()
    
    try:
        # Test ticker stream
        print("Testing ticker stream...")
        tick_count = 0
        async for tick in gateway.stream_ticker(["RELIANCE"], Exchange.NSE):
            tick_count += 1
            if tick_count <= 3:
                print(f"  Tick {tick_count}: {tick.instrument.symbol} @ {tick.price}")
            if tick_count >= 5:
                break
        
        print(f"✓ Ticker stream working ({tick_count} ticks received)")
        
        # Test quote stream
        print("Testing quote stream...")
        quote_count = 0
        async for quote in gateway.stream_quotes(["TCS"], Exchange.NSE):
            quote_count += 1
            if quote_count <= 3:
                print(f"  Quote {quote_count}: {quote.instrument.symbol} LTP={quote.ltp}")
            if quote_count >= 5:
                break
        
        print(f"✓ Quote stream working ({quote_count} quotes received)")
        
        print("✅ Live streaming test PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Live streaming test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        gateway.close()


async def test_async_context_manager():
    """Test async context manager with all operations."""
    print("\n=== Testing Async Context Manager Integration ===")
    
    try:
        async with BrokerGateway.paper() as gateway:
            print("✓ Entered async context")
            
            # Test quote
            quote = gateway.get_quote("INFY", Exchange.NSE)
            print(f"✓ Quote: {quote.instrument.symbol} @ {quote.ltp}")
            
            # Test option chain
            chain = gateway.get_option_chain("BANKNIFTY", Exchange.NFO)
            print(f"✓ Option chain: {chain.underlying.symbol}")
            
            # Test streaming (brief)
            tick_count = 0
            async for tick in gateway.stream_ticker(["RELIANCE"], Exchange.NSE):
                tick_count += 1
                if tick_count >= 2:
                    break
            
            print(f"✓ Streaming: {tick_count} ticks received")
            
        print("✓ Exited async context (cleanup successful)")
        print("✅ Async context manager integration test PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Async context manager test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    results = []
    
    try:
        # Run sync tests
        results.append(("Historical Data", test_historical_data()))
        results.append(("Options Chain", test_options_chain()))
        
        # Run async tests
        results.append(("Live Streaming", asyncio.run(test_live_streaming())))
        results.append(("Async Context Manager", asyncio.run(test_async_context_manager())))
        
        # Summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        for name, passed in results:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{status} - {name}")
        
        all_passed = all(passed for _, passed in results)
        print("="*60)
        if all_passed:
            print("🎉 ALL TESTS PASSED - Core broker functionality working")
        else:
            print("⚠️  SOME TESTS FAILED - Check output above")
            sys.exit(1)
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
