"""Fetch authoritative lot sizes from Dhan's instrument master."""
import asyncio
import os
import sys

from dotenv import load_dotenv

ROOT = "/Users/apple/Documents/v5-of-glassytrade-ai"
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from brokers.broker.entities import Exchange, Instrument  # noqa: E402
from brokers.broker.dhan.infrastructure import DhanSymbolMapper  # noqa: E402


async def main() -> None:
    mapper = DhanSymbolMapper()
    await mapper.refresh_cache()
    print(f"instruments in cache: {len(mapper._instruments)}")
    # find option instruments for the three underlyings, current expiry
    from brokers.broker.dhan.infrastructure.symbol_mapper import ExchangeSegment
    from brokers.broker.dhan.domain.constants import INDEX_UNDERLYINGS

    seen = {}
    for inst in mapper._instruments:
        seg = inst.get("SEM_EXM_EXCH_ID") or inst.get("exchange") or ""
        sym = inst.get("SEM_TRADING_SYMBOL") or inst.get("tradingSymbol") or ""
        lot = inst.get("SEM_LOT_SIZE") or inst.get("lotSize") or inst.get("lot_size")
        if not sym or not lot:
            continue
        for u in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
            if sym.startswith(u) and "CE" in sym and "26" not in sym[:8]:
                seen.setdefault(u, (sym, seg, lot))
    for u, (sym, seg, lot) in seen.items():
        print(f"{u}: {sym} | seg={seg} | lot_size={lot}")


if __name__ == "__main__":
    asyncio.run(main())
