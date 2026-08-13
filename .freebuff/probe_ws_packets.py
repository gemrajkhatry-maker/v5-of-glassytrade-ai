"""Tap the live Dhan WS FULL feed and simulate the multiplexed-feed conversion.

Counts packet types and feeds consecutive packets through the same
_cum_to_delta logic to show whether TICKER packets (no volume) reset the
baseline and cap the next real delta at 10,000.
"""
import asyncio
import os
import sys
from collections import Counter

from dotenv import load_dotenv

ROOT = "/Users/apple/Documents/v5-of-glassytrade-ai"
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from backend.app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter  # noqa: E402

SYMBOL = "NIFTY 11 AUG 24600 CALL"


async def main() -> None:
    adapter = DhanMarketDataAdapter(
        symbols=["NIFTY"],
        exchange="NFO",
        client_id=os.environ.get("DHAN_CLIENT_ID"),
        access_token=os.environ.get("DHAN_ACCESS_TOKEN"),
    )
    try:
        await adapter._ensure_initialized()
        broker = adapter.get_broker()
        ws = broker._streaming._get_persistent_ws  # may be sync method
        # Use the broker's streaming service directly to see RAW message types.
        from brokers.broker.entities import Exchange, Instrument

        inst = Instrument(symbol=SYMBOL, exchange=Exchange.NFO, option_type="CALL")
        stream = adapter.stream_full([SYMBOL])
        counts = Counter()
        prev = None
        total_delta = 0.0
        capped = 0
        resets = 0
        start = asyncio.get_event_loop().time()
        n = 0
        seq = []
        async for pkt in stream:
            n += 1
            vol = float(pkt.get("volume") or 0)
            seq.append((vol, float(pkt.get("total_buy_qty") or 0), float(pkt.get("total_sell_qty") or 0)))
            main.seq = seq
            buy = float(pkt.get("total_buy_qty") or 0)
            sell = float(pkt.get("total_sell_qty") or 0)
            # classify: ticker = no volume at all
            if vol == 0 and buy == 0 and sell == 0:
                counts["ticker(no-vol)"] += 1
            else:
                counts["full/quote(with-vol)"] += 1
            # simulate _cum_to_delta (copy of the real logic)
            if not (vol == 0 and buy == 0 and sell == 0):
                if prev is None:
                    prev = (vol, buy, sell)
                    delta = (0.0, 0.0, 0.0)
                else:
                    pvol, pbuy, psell = prev
                    if vol < pvol or buy < pbuy or sell < psell:
                        resets += 1
                        prev = (vol, buy, sell)
                        delta = (0.0, 0.0, 0.0)
                    else:
                        dvol = max(0.0, vol - pvol)
                        cap = max(10000.0, pvol * 0.05) if pvol > 0 else 10000.0
                        if dvol > cap:
                            dvol = cap
                            capped += 1
                        prev = (vol, buy, sell)
                        delta = (dvol, 0.0, 0.0)
                total_delta += delta[0]
            else:
                # ticker: real feed does NOT touch baseline; old feed DID (reset)
                pass
            if asyncio.get_event_loop().time() - start > 25:
                break
        print(f"packets in ~25s: {n} | {dict(counts)}")
        print(f"simulated accumulated volume: {total_delta:,.0f}")
        print(f"capped ticks: {capped} | genuine backwards-resets: {resets}")
        print(f"last cumulative seen: {prev[0]:,.0f} if prev else None")
        seq = getattr(main, "seq", None)
        if seq:
            print("raw (vol, buy, sell) sequence:")
            for i, v in enumerate(seq):
                print(f"  {i}: {v}")
    finally:
        adapter.close_sync()


if __name__ == "__main__":
    asyncio.run(main())
