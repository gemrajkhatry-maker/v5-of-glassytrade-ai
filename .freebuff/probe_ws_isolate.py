"""Isolate WS rejection: NSE vs MCX, and MCX segment variants."""
import asyncio
import json
import os
import sys

from dotenv import load_dotenv

ROOT = "/Users/apple/Documents/v5-of-glassytrade-ai"
load_dotenv(os.path.join(ROOT, ".env"))

import websockets  # noqa: E402

TOKEN = os.environ.get("DHAN_ACCESS_TOKEN", "")
CLIENT = os.environ.get("DHAN_CLIENT_ID", "")
URL = f"wss://api-feed.dhan.co?version=2&token={TOKEN}&clientId={CLIENT}&authType=2"

CASES = [
    ("NSE_FNO NIFTY CE 41017", [{"SecurityId": "41017", "ExchangeSegment": "NSE_FNO"}]),
    ("MCX_COMM CRUDEOIL 573470", [{"SecurityId": "573470", "ExchangeSegment": "MCX_COMM"}]),
    ("MCX_FNO CRUDEOIL 573470", [{"SecurityId": "573470", "ExchangeSegment": "MCX_FNO"}]),
    ("MCX_COMM int7 CRUDEOIL 573470", [{"SecurityId": "573470", "ExchangeSegment": 7}]),
    ("NSE_EQ index NIFTY 50", [{"SecurityId": "13", "ExchangeSegment": "NSE_EQ"}]),
]


async def try_subscribe(label, instruments, timeout=10.0):
    payload = {"RequestCode": 21, "InstrumentCount": len(instruments), "InstrumentList": instruments}
    try:
        async with websockets.connect(URL, open_timeout=10) as ws:
            await ws.send(json.dumps(payload))
            got = 0
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    got += 1
                    if isinstance(msg, bytes):
                        print(f"  {label}: pkt #{got} ({len(msg)}B) LIVE")
                        if got >= 2:
                            print(f"  {label}: RESULT ALIVE")
                            return
                    else:
                        print(f"  {label}: text: {msg[:100]}")
            except asyncio.TimeoutError:
                print(f"  {label}: RESULT QUIET (accepted, no data)")
            except websockets.ConnectionClosed as e:
                print(f"  {label}: RESULT CLOSED ({e.code} {e.reason}) after {got} pkts")
    except Exception as e:
        print(f"  {label}: CONNECT_FAIL {type(e).__name__}: {e}")


async def main():
    print(f"client={CLIENT} token_len={len(TOKEN)}")
    for label, insts in CASES:
        await try_subscribe(label, insts)
        print()


asyncio.run(main())
