import pandas as pd
from brokers.broker.dhan.infrastructure.symbol_mapper import DhanSymbolMapper
import asyncio

async def main():
    mapper = DhanSymbolMapper()
    await mapper.refresh_cache()
    df = mapper._instrument_df
    
    # 249304 is the row index in the dataframe
    if df is not None:
        try:
            row = df.loc[249304]
            print("\n--- Row 249304 details ---")
            for col, val in row.items():
                print(f"{col}: {val}")
        except Exception as e:
            print(f"Error: {e}")
            
    # And check if there are any actual NSE_IFSC instruments in Dhan
    if df is not None:
        if 'SEM_EXM_EXCH_ID' in df.columns:
            print("\nUnique Exchange IDs:")
            print(df['SEM_EXM_EXCH_ID'].unique())
            
        print("\nChecking any symbol name matching GIFT")
        matches = df[df['SM_SYMBOL_NAME'].str.contains('GIFT', na=False, case=False) if 'SM_SYMBOL_NAME' in df.columns else df['SEM_SMST_SYMBOL_NAME'].str.contains('GIFT', na=False, case=False)]
        print(f"Rows matching 'GIFT': {len(matches)}")
        for _, r in matches.iterrows():
            print(f"SecID: {r.get('SEM_SMST_SECURITY_ID')} | Exch: {r.get('SEM_EXM_EXCH_ID')} | Symbol: {r.get('SEM_TRADING_SYMBOL', r.get('SM_SYMBOL_NAME'))}")

if __name__ == "__main__":
    asyncio.run(main())
