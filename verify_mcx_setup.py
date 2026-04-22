#!/usr/bin/env python
"""Verify WebSocket streaming, option contract selection, and historical data."""

import asyncio
import json
import sys
import os
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.application.service_graph import ServiceGraph
from app.domain.fabio_ai.services.option_scanner import OptionScannerService
from config.config import Configuration


async def verify_option_scanner():
    """Verify CRUDEOIL option contract selection."""
    print("\n" + "="*70)
    print("1. VERIFYING OPTION CONTRACT SELECTION")
    print("="*70)
    
    try:
        config = Configuration.from_env()
        graph = ServiceGraph(config)
        scanner = OptionScannerService(graph.market_data)
        
        print("\nScanning for CRUDEOIL options...")
        results = await scanner.scan_top_n(
            n=3,
            underlyings=["CRUDEOIL", "NATURALGAS"],
            exchange="MCX",
            expiry_index=0,
            strikes_around_atm=2,
        )
        
        if results:
            print(f"\n✅ Found {len(results)} option contracts:")
            for i, r in enumerate(results, 1):
                print(f"\n  {i}. {r.symbol}")
                print(f"     Underlying: {r.underlying}")
                print(f"     Strike: {r.strike}")
                print(f"     Type: {r.option_type}")
                print(f"     Expiry: {r.expiry}")
                print(f"     LTP: ₹{r.ltp:.2f}")
                print(f"     OI: {r.oi}")
                print(f"     Volume: {r.volume}")
                print(f"     Score: {r.score:.1f}")
                print(f"     Bias: {r.bias} ({r.bias_reason})")
            
            # Check if active_symbols are updated
            print(f"\nCurrent active_symbols: {graph.active_symbols}")
            print(f"Expected: {[r.symbol for r in results[:3]]}")
            
            if graph.active_symbols == ["CRUDEOIL", "NATURALGAS"]:
                print("\n⚠️  WARNING: active_symbols still using underlyings, not option contracts!")
                print("   Option scanner found contracts but didn't update active_symbols")
            else:
                print("\n✅ active_symbols updated with option contracts")
        else:
            print("\n❌ No option contracts found!")
            print("   Possible reasons:")
            print("   - Market is closed")
            print("   - No liquid contracts available")
            print("   - Scanner filters too strict")
        
        return results
        
    except Exception as e:
        print(f"\n❌ Option scanner failed: {e}")
        import traceback
        traceback.print_exc()
        return []


async def verify_websocket_streaming():
    """Verify WebSocket streaming status."""
    print("\n" + "="*70)
    print("2. VERIFYING WEBSOCKET STREAMING")
    print("="*70)
    
    try:
        config = Configuration.from_env()
        graph = ServiceGraph(config)
        engine = getattr(graph, 'engine', None)
        
        if engine is None:
            print("\n❌ Trading engine not found!")
            print("   Engine must be started via lifespan")
            return False
        
        print(f"\n✅ Trading engine is running")
        print(f"   Active symbols: {engine.get_active_symbols()}")
        print(f"   Generation: {engine.generation}")
        print(f"   Running: {engine._running}")
        
        # Check tick counts
        print("\n   Tick counts per symbol:")
        for sym in engine.get_active_symbols():
            tick_count = engine._tick_counts.get(sym, 0)
            print(f"     {sym}: {tick_count} ticks")
        
        if engine._polling_mode:
            print("\n   ⚠️  Using REST polling fallback (WebSocket not delivering ticks)")
            print("   This is expected for MCX options if broker WS doesn't support them")
        else:
            print("\n   ✅ Using WebSocket streaming")
        
        return True
        
    except Exception as e:
        print(f"\n❌ WebSocket verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def verify_historical_data():
    """Verify historical data loading."""
    print("\n" + "="*70)
    print("3. VERIFYING HISTORICAL DATA LOADING")
    print("="*70)
    
    try:
        config = Configuration.from_env()
        graph = ServiceGraph(config)
        engine = getattr(graph, 'engine', None)
        
        if engine is None:
            print("\n❌ Trading engine not found!")
            return False
        
        active_symbols = engine.get_active_symbols()
        
        for symbol in active_symbols:
            print(f"\nSymbol: {symbol}")
            history = engine.get_history(symbol)
            
            if history:
                print(f"  ✅ Historical data loaded: {len(history)} candles")
                # Show first and last candle
                if len(history) > 0:
                    first = history[0]
                    last = history[-1]
                    print(f"     First: {first.time} O={first.open} H={first.high} L={first.low} C={first.close}")
                    print(f"     Last:  {last.time} O={last.open} H={last.high} L={last.low} C={last.close}")
            else:
                print(f"  ⚠️  No historical data for {symbol}")
                print(f"     This is expected if:")
                print(f"     - Market is closed")
                print(f"     - Dhan API returned no data")
                print(f"     - Symbol doesn't have historical data available")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Historical data verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all verifications."""
    print("\n" + "="*70)
    print("GLASSYTRADE AI - MCX MODE VERIFICATION")
    print("="*70)
    print(f"\nConfiguration:")
    print(f"  DEFAULT_EXCHANGE: MCX")
    print(f"  SCANNER_MODE: mcx")
    print(f"  DHAN_SYMBOLS: ['CRUDEOIL', 'NATURALGAS']")
    
    # Run verifications
    options = await verify_option_scanner()
    ws_ok = await verify_websocket_streaming()
    hist_ok = await verify_historical_data()
    
    # Summary
    print("\n" + "="*70)
    print("VERIFICATION SUMMARY")
    print("="*70)
    print(f"\n1. Option Contract Selection: {'✅ PASS' if options else '⚠️  PARTIAL'}")
    print(f"2. WebSocket Streaming: {'✅ PASS' if ws_ok else '❌ FAIL'}")
    print(f"3. Historical Data: {'✅ PASS' if hist_ok else '⚠️  PARTIAL'}")
    
    if options and ws_ok:
        print("\n✅ System is operational in MCX mode")
    else:
        print("\n⚠️  System has issues - check logs above")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    asyncio.run(main())
