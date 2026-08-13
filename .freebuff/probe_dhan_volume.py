"""Probe Dhan volume units: option-chain day volume (contracts) vs live WS `Vol`.

Uses the same DhanMarketDataAdapter the app wires, so symbol resolution works.
Prints:
  * option-chain per-strike volume (Dhan docs: day contracts) + OI for 24600 CE
  * the latest live WS FULL packet's cumulative volume / ltq / buy / sell
  * today's REST 5m bar volumes (sum + max)
"""
import asyncio
import os
import sys
from datetime import datetime, time, timedelta

from dotenv import load_dotenv

ROOT = "/Users/apple/Documents/v5-of-glassytrade-ai"
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from brokers.broker.entities import Exchange, Instrument  # noqa: E402
from backend.app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter  # noqa: E402

SYMBOL = "NIFTY 11 AUG 24600 CALL"
UNDERLYING = "NIFTY"
STRIKE = 24600.0


async def main() -> None:
    adapter = DhanMarketDataAdapter(
        symbols=[UNDERLYING],
        exchange="NFO",
        client_id=os.environ.get("DHAN_CLIENT_ID"),
        access_token=os.environ.get("DHAN_ACCESS_TOKEN"),
    )
    try:
        await adapter._ensure_initialized()
        broker = adapter.get_broker()

        # 1) Option chain — day volume per strike (contracts per Dhan docs)
        chain = await broker.get_option_chain_async(UNDERLYING, Exchange.NSE, 0)
        print("expiry:", chain.expiry, "| spot:", chain.spot_price)
        opt = chain.calls.get(STRIKE) or chain.puts.get(STRIKE)
        if opt is None:
            all_calls = sorted(
                chain.calls.values(), key=lambda o: abs(o.strike - chain.spot_price)
            )
            opt = all_calls[0]
            print(f"strike {STRIKE} not found; using nearest {opt.strike}")
        print(f"chain {opt.symbol}: volume={opt.volume} day-contracts, oi={opt.oi}, "
              f"prev_volume={opt.prev_volume}, ltp={opt.ltp}")

        # 2) Live WS cumulative Vol for the same contract (~25s)
        latest = {}
        async for pkt in adapter.stream_full([SYMBOL]):
            latest = pkt
            if len(latest) > 0:
                break
        # keep reading a few seconds to get a settled packet
        import asyncio as aio

        end = aio.get_event_loop().time() + 12
        while aio.get_event_loop().time() < end:
            try:
                async for pkt in adapter.stream_full([SYMBOL]):
                    latest = pkt
                    break
            except Exception:
                pass
            await aio.sleep(3)
        print(f"WS latest: volume={latest.get('volume')} ltq={latest.get('ltq')} "
              f"total_buy_qty={latest.get('total_buy_qty')} "
              f"total_sell_qty={latest.get('total_sell_qty')} ltp={latest.get('ltp')}")

        # 3) Today's REST 5m candles
        today = datetime.combine(datetime.now().date(), time.min)
        inst = Instrument(symbol=SYMBOL, exchange=Exchange.NFO, option_type="CALL")
        df = await broker.get_historical_async(inst, today, today + timedelta(days=1), interval="5")
        if df is None or df.empty:
            print("no 5m REST history returned")
        else:
            vols = [float(v) for v in df["volume"]]
            print(f"REST 5m: {len(vols)} bars | sum={sum(vols):,.0f} | max/bar={max(vols):,.0f}")

        # 4) Unit ratios
        chain_v = opt.volume or 0
        ws_v = latest.get("volume") or 0
        if chain_v > 0:
            print(f"ws_cumulative/chain_day = {ws_v/chain_v:.3f}  "
                  f"(~1.0 => WS Vol IS day contracts; >>1 => different unit)")
        if df is not None and not df.empty and chain_v > 0:
            print(f"sum(REST 5m)/chain_day = {sum(vols)/chain_v:.3f}")
    finally:
        adapter.close_sync()


if __name__ == "__main__":
    asyncio.run(main())
