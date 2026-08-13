"""Probe the gameloop WS with `websockets` (async): subscribe and dump the
first full snapshot + deltas, checking whether `amt` is populated."""
import asyncio
import json

import websockets


async def main():
    async with websockets.connect("ws://127.0.0.1:9090/ws/gameloop", origin="http://127.0.0.1:5190") as ws:
        await ws.send(json.dumps({"subscribe": "CRUDEOIL 17 AUG 7450 CALL"}))
        n = 0
        while n < 8:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=8)
            except asyncio.TimeoutError:
                print("TIMEOUT waiting for msg", n)
                break
            n += 1
            try:
                msg = json.loads(raw)
            except Exception:
                print("BAD_JSON", raw[:200])
                continue
            t = msg.get("_type") or msg.get("status") or "?"
            keys = sorted(msg.keys())
            if t == "full":
                amt = msg.get("amt")
                print(f"[{n}] _type=full keys={keys}")
                print(f"    amt={'None' if amt is None else 'dict'}")
                if amt:
                    print(f"    amt.marketState={amt.get('marketState')} poc={amt.get('poc')}")
                print(f"    genAIAnalysis={'None' if msg.get('genAIAnalysis') is None else 'dict'}")
                print(f"    quantDecision={'None' if msg.get('quantDecision') is None else 'dict'}")
                print(f"    tick={'None' if msg.get('tick') is None else 'dict'}")
            elif t == "delta":
                if "amt" in msg:
                    print(f"[{n}] delta contains amt={'dict' if msg['amt'] is not None else 'None'}")
                if "tick" in msg:
                    print(f"[{n}] delta tick: {str(msg['tick'])[:120]}")
            else:
                print(f"[{n}] {t} keys={keys}")
            if t == "full" and n >= 4:
                break
            await asyncio.sleep(0.6)


asyncio.run(main())
print("DONE")
