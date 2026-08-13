"""Raw Dhan WS probe: subscribe to the current 4 MCX IDs, then bisect one at a time.

Uses the exact URL/auth the app uses (websocket_client.py):
  wss://api-feed.dhan.co?version=2&token=TOKEN&clientId=CLIENT_ID&authType=2
"""
import asyncio
import json
import os
import sys

from dotenv import load_dotenv

ROOT = "/Users/apple/Documents/v5-of-glassytrade-ai"
load_dotenv(os.path.join(ROOT, ".env"))

try:
    import websockets
except ImportError:
    print("NO_WEBSOCKETS_LIB")
    sys.exit(2)

TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "")
CLIENT = os.environ.get("DHAN_CLIENT_ID", "")
URL = f"wss://api-feed.dhan.co?version=2&token={TOKEN}&clientId={CLIENT}&authType=2"

ALL_IDS = ["560392", "575030", "573470", "574334"]
SEGMENT = "MCX_COMM"


def sub_payload(ids):
    return {
        "RequestCode": 21,
        "InstrumentCount": len(ids),
        "InstrumentList": [
            {"SecurityId": sid, "ExchangeSegment": SEGMENT} for sid in ids
        ],
    }


async def try_subscribe(ids, label, timeout=12.0):
    try:
        async with websockets.connect(URL, open_timeout=10) as ws:
            await ws.send(json.dumps(sub_payload(ids)))
            print(f"{label}: sent subscribe for {ids}")
            got = 0
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    got += 1
                    if isinstance(msg, bytes):
                        print(f"{label}: recv binary pkt #{got} ({len(msg)}B) -> LIVE")
                        # keep going; if it survives a few packets, good enough
                        if got >= 3:
                            print(f"{label}: RESULT ALIVE ({got} packets, no close)")
                            return "ALIVE"
                    else:
                        print(f"{label}: recv text: {msg[:120]}")
            except asyncio.TimeoutError:
                print(f"{label}: RESULT QUIET (no close, no data in {timeout}s) -> likely accepted")
                return "QUIET"
            except websockets.ConnectionClosed as e:
                print(f"{label}: RESULT CLOSED ({e.code} {e.reason}) after {got} pkts")
                return "CLOSED"
    except Exception as e:
        print(f"{label}: CONNECT_FAIL {type(e).__name__}: {e}")
        return "CONNECT_FAIL"


async def main():
    print(f"client={CLIENT} token_len={len(TOKEN)} url_host=api-feed.dhan.co")
    # 1) all 4 together (exactly what the app sends)
    r_all = await try_subscribe(ALL_IDS, "ALL4")
    print()
    # 2) bisect: one at a time
    for sid in ALL_IDS:
        await try_subscribe([sid], f"ONE[{sid}]")
        print()


asyncio.run(main())
