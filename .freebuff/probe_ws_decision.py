import asyncio, json, sys

import websockets

URL = "ws://127.0.0.1:9090/api/trading/ws/gameloop"
SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "NIFTY 11 AUG 24600 CALL"
TIMEOUT = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0


async def main():
    async with websockets.connect(URL) as ws:
        await ws.send(json.dumps({"subscribe": SYMBOL}))
        deadline = asyncio.get_event_loop().time() + TIMEOUT
        while asyncio.get_event_loop().time() < deadline:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            except asyncio.TimeoutError:
                continue
            if not isinstance(msg, dict) or msg.get("_type") == "delta":
                continue
            if "quantDecision" not in msg:
                continue
            qd = msg.get("quantDecision") or {}
            agent = msg.get("agentDecision") or {}
            auc = msg.get("auction") or {}
            print(json.dumps({
                "ltp": msg.get("ltp"),
                "auction": {
                    "time": auc.get("time"),
                    "phase": auc.get("tripleAPhase"),
                    "signal": auc.get("tripleASignal"),
                },
                "quantDecision": {
                    "approved": qd.get("approved"),
                    "reason": qd.get("reason"),
                    "phase": qd.get("phase"),
                    "gates": [
                        {"g": g.get("gate"), "pass": g.get("passed"), "why": g.get("reason")}
                        for g in qd.get("gateResults", [])
                    ],
                    "signal": qd.get("signal"),
                },
                "agentDecision": {
                    "direction": agent.get("direction"),
                    "probability": agent.get("probability"),
                },
            }))
            return
        print("no full snapshot with quantDecision in window")


asyncio.run(main())
