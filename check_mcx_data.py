#!/usr/bin/env python3
"""Check historical data for gaps in MCX symbols."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'brokers'))

import asyncio
from datetime import datetime, timedelta
from pytz import timezone

from broker.dhan.broker import DhanBroker
from broker.dhan.models.instrument import Instrument
from broker.dhan.domain.errors import DhanSymbolNotFoundError

IST = timezone('Asia/Kolkata')

async def check_historical_data():
    """Fetch and analyze historical data for gaps."""
    
    # Initialize broker
    broker = DhanBroker()
    await broker.initialize_async()
    
    # Test symbols
    symbols_to_check = [
        ("CRUDEOIL", "MCX", "5m"),
        ("GOLDM", "MCX", "5m"),
    ]
    
    for symbol, exchange, interval in symbols_to_check:
        print(f"\n{'='*60}")
        print(f"Checking {symbol} ({exchange}) - {interval} interval")
        print(f"{'='*60}")
        
        try:
            # Get instrument
            instrument = broker.symbol_mapper.get_instrument(
                symbol=symbol,
                exchange=exchange,
                product_type="MIS",  # Intraday
                instrument_type="OPTIONS",
                strike_price="8300",
                expiry_date="14 MAY 2025"
            )
            
            # Fetch last 5 days of data
            to_date = datetime.now(IST)
            from_date = to_date - timedelta(days=5)
            
            print(f"Fetching from {from_date} to {to_date}...")
            
            df = await broker.historical.get_historical_async(
                instrument=instrument,
                from_date=from_date,
                to_date=to_date,
                interval=interval,
                include_oi=False
            )
            
            if df.empty:
                print("❌ No data returned!")
                continue
            
            print(f"✅ Loaded {len(df)} candles")
            print(f"   Time range: {df.index[0]} to {df.index[-1]}")
            
            # Check for time gaps
            df_sorted = df.sort_index()
            time_diffs = df_sorted.index.to_series().diff().dropna()
            
            if len(time_diffs) > 0:
                avg_diff = time_diffs.mean()
                max_diff = time_diffs.max()
                min_diff = time_diffs.min()
                
                print(f"\n   Time gap analysis:")
                print(f"   - Average gap: {avg_diff}")
                print(f"   - Max gap: {max_diff}")
                print(f"   - Min gap: {min_diff}")
                
                # Find gaps > 2x average
                threshold = avg_diff * 2
                large_gaps = time_diffs[time_diffs > threshold]
                
                if len(large_gaps) > 0:
                    print(f"\n   ⚠️  Found {len(large_gaps)} large gaps (>{threshold}):")
                    for gap_time, gap_duration in large_gaps.items():
                        print(f"      - {gap_time}: {gap_duration}")
                else:
                    print(f"\n   ✅ No significant gaps found")
                
                # Check for missing candles during market hours
                market_hours_mask = (
                    (df_sorted.index.hour >= 9) & 
                    (df_sorted.index.hour < 18)  # MCX hours ~9AM-11:30PM IST
                )
                
                market_candles = df_sorted[market_hours_mask]
                print(f"\n   Market hours candles: {len(market_candles)}")
                
                # Show first 5 and last 5 candles
                print(f"\n   First 5 candles:")
                for idx, row in df_sorted.head(5).iterrows():
                    print(f"      {idx}: O={row['open']} H={row['high']} L={row['low']} C={row['close']} V={row['volume']}")
                
                print(f"\n   Last 5 candles:")
                for idx, row in df_sorted.tail(5).iterrows():
                    print(f"      {idx}: O={row['open']} H={row['high']} L={row['low']} C={row['close']} V={row['volume']}")
            
        except DhanSymbolNotFoundError as e:
            print(f"❌ Symbol not found: {e}")
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    await broker.close()

if __name__ == "__main__":
    asyncio.run(check_historical_data())
