import pandas as pd
from brokers.broker.dhan.infrastructure.symbol_mapper import DhanSymbolMapper
import asyncio

async def main():
    mapper = DhanSymbolMapper()
    await mapper.refresh_cache()
    df = mapper._instrument_df
    
    if df is not None:
        symbol_col = 'SEM_SMST_SYMBOL_NAME' if 'SEM_SMST_SYMBOL_NAME' in df.columns else 'SM_SYMBOL_NAME'
        
        matches = df[df[symbol_col].str.contains('GIFT', na=False, case=False) | df['SEM_TRADING_SYMBOL'].str.contains('GIFT', na=False, case=False)]
        for idx, r in matches.iterrows():
            print(f"Index: {idx}, SecID: {r.get('SEM_SMST_SECURITY_ID')}, Exch: {r.get('SEM_EXM_EXCH_ID')}, Symbol: {r.get('SEM_TRADING_SYMBOL')}, InstType: {r.get('SEM_INSTRUMENT_NAME')}")
            
if __name__ == "__main__":
    asyncio.run(main())
