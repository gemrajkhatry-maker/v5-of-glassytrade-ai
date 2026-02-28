import asyncio
from datetime import datetime
from brokers.broker.dhan.infrastructure.symbol_mapper import DhanSymbolMapper
from brokers.broker.dhan.domain import ExchangeSegment

async def main():
    print("Initializing DhanSymbolMapper...")
    mapper = DhanSymbolMapper()
    
    print("Refreshing instrument cache (this will download the latest CSV from Dhan)...")
    await mapper.refresh_cache()
    
    print(f"Total instruments loaded: {len(mapper._by_security_id)}")
    
    df = mapper._instrument_df
    if df is not None:
        print("\nChecking raw DataFrame for NSE_IFSC ...")
        # Let's inspect unique exchange codes in the CSV
        exchanges = df.get('SEM_EXM_EXCH_ID', df.get('EXCH_ID', None))
        if exchanges is not None:
            print(f"Unique exchanges found in Dhan CSV: {exchanges.dropna().unique().tolist()}")
        
        symbol_col = 'SEM_SMST_SYMBOL_NAME' if 'SEM_SMST_SYMBOL_NAME' in df.columns else 'SM_SYMBOL_NAME'
        
        # Search for GIFTNIFTY50
        print(f"\nSearching for GIFTNIFTY50 or NSE_IFSC options using {symbol_col}...")
        
        matches = df[
            df['SEM_TRADING_SYMBOL'].str.contains('GIFT', na=False, case=False) |
            (df[symbol_col].str.contains('GIFT', na=False, case=False) if symbol_col in df.columns else False)
        ]
        
        print(f"Found {len(matches)} raw rows matching 'GIFT'")
        if not matches.empty:
            cols_to_print = [c for c in ['SEM_EXM_EXCH_ID', 'SEM_INSTRUMENT_NAME', 'SEM_TRADING_SYMBOL', symbol_col] if c in df.columns]
            print(matches[cols_to_print].head(10))
            
        print("\nChecking if there's any OPTIDX for GIFTNIFTY50...")
        optidx_gift = df[
            (df['SEM_INSTRUMENT_NAME'] == 'OPTIDX') & 
            (df[symbol_col].str.contains('GIFTNIFTY', na=False, case=False) if symbol_col in df.columns else False)
        ]
        print(f"Found {len(optidx_gift)} OPTIDX for GIFTNIFTY")
        if not optidx_gift.empty:
             cols_to_print = [c for c in ['SEM_EXM_EXCH_ID', 'SEM_INSTRUMENT_NAME', 'SEM_TRADING_SYMBOL', symbol_col] if c in df.columns]
             print(optidx_gift[cols_to_print].head())
             
        # Check exchange segment precisely as NSE_IFSC
        is_nse_ifsc = df[df.get('SEM_EXM_EXCH_ID', '') == 'NSE_IFSC']
        print(f"\nFound {len(is_nse_ifsc)} rows with exchange == 'NSE_IFSC'")
        if not is_nse_ifsc.empty:
            cols_to_print = [c for c in ['SEM_EXM_EXCH_ID', 'SEM_INSTRUMENT_NAME', 'SEM_TRADING_SYMBOL'] if c in df.columns]
            print(is_nse_ifsc[cols_to_print].head())
            
    else:
        print("Could not access raw dataframe.")

if __name__ == "__main__":
    asyncio.run(main())
