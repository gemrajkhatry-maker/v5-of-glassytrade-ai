import asyncio
import json
import websockets

TARGET_SYMBOLS = ["CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"]

async def inspect_gameloop():
    uri = "ws://localhost:8090/api/trading/ws/gameloop"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri, ping_interval=10, ping_timeout=10) as ws:
            print("Connected to gameloop! Sending subscription for CRUDEOIL...")
            await ws.send(json.dumps({"subscribe": "CRUDEOIL"}))
            
            seen = {}
            for i in range(120):
                msg_str = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(msg_str)
                
                # If handshake message, ignore
                if data.get("status") == "server_mode":
                    continue

                msg_type = data.get("type")
                # Handle delta payloads or direct snapshots
                payloads = []
                if msg_type == "delta" and isinstance(data.get("data"), list):
                    for item in data.get("data", []):
                        if isinstance(item, dict):
                            payloads.append(item)
                elif "data" in data and isinstance(data["data"], dict):
                    payloads.append(data["data"])
                elif "symbol" in data:
                    payloads.append(data)
                
                for payload in payloads:
                    symbol = payload.get("symbol")
                    if not symbol:
                        continue
                    
                    matched_key = None
                    for target in TARGET_SYMBOLS:
                        if target in symbol and "FUT" in symbol:
                            matched_key = target
                            break
                    
                    if matched_key and matched_key not in seen:
                        seen[matched_key] = True
                        print(f"\n========================================================")
                        print(f"=== LIVE DATA & DECISION AUDIT: {symbol} ===")
                        print(f"========================================================")
                        print(f"Payload Type: {msg_type} | Symbol: {symbol}")
                        
                        # 1. Market & AMT Data
                        amt = payload.get("amt") or {}
                        ltp = payload.get("ltp") or amt.get("close")
                        print(f"\n[1. Market & AMT Data Quality]")
                        print(f"  • LTP: {ltp}")
                        print(f"  • Session Range: [{amt.get('sessionLow')}, {amt.get('sessionHigh')}]")
                        print(f"  • Market State: {amt.get('marketState')} | Sub-state / Zone: {amt.get('marketZone')}")
                        print(f"  • Value Area: VAL={amt.get('val')}, POC={amt.get('poc')}, VAH={amt.get('vah')}")
                        print(f"  • VWAP: {amt.get('vwap')} | CVD: {amt.get('cvd')}")
                        print(f"  • Leg Profile: POC={amt.get('legPoc')}, VA=[{amt.get('legVal')}, {amt.get('legVah')}]")
                        
                        # 2. Decision Making & Strategy
                        qd = payload.get("quantDecision") or {}
                        print(f"\n[2. Quant Strategy & Decision Making]")
                        print(f"  • Action: {qd.get('action')}")
                        print(f"  • Setup: {qd.get('setup')}")
                        print(f"  • Direction: {qd.get('direction')}")
                        print(f"  • Reason: {qd.get('reason')}")
                        print(f"  • Conviction: {qd.get('conviction')} ({qd.get('confidence')}%)")
                        
                        # 3. 4-Gate Pipeline
                        gates = qd.get("gates") or []
                        print(f"\n[3. 4-Gate Pipeline Validation]")
                        if isinstance(gates, list):
                            for g in gates:
                                status_str = "PASS" if g.get("passed") else "FAIL / BLOCKED"
                                print(f"  • Gate {g.get('name')}: {status_str} | Reason: {g.get('reason')}")
                        elif isinstance(gates, dict):
                            for k, v in gates.items():
                                print(f"  • Gate {k}: {v}")
                        else:
                            print(f"  • Gates: {gates}")
                            
                        # 4. TimesFM 3.0 Native Advisor
                        tfm = payload.get("timesfm") or qd.get("timesfm") or {}
                        print(f"\n[4. TimesFM 3.0 Native Advisor Forecast]")
                        print(f"  • Status: {tfm.get('status')}")
                        print(f"  • Mode: {tfm.get('mode', 'NATIVE')}")
                        print(f"  • Forecast Direction: {tfm.get('forecast')} | Drift: {tfm.get('drift_pct')}%")
                        print(f"  • Steps: {tfm.get('bullish_steps')}/{tfm.get('total_steps')} Bullish Steps")
                        print(f"  • Confidence: {tfm.get('confidence')}")

                        # 5. Risk Management State
                        risk = payload.get("risk") or {}
                        print(f"\n[5. Risk Management Guardrails]")
                        print(f"  • Halted: {risk.get('halted')}")
                        print(f"  • Daily PnL: ₹{risk.get('daily_pnl')}")
                        print(f"  • Consecutive Losses: {risk.get('consecutive_losses')}")
                        print(f"  • Max Drawdown: ₹{risk.get('max_drawdown')}")
                        print(f"  • Active Positions: {payload.get('positions', [])}")
                
                if len(seen) >= len(TARGET_SYMBOLS):
                    print(f"\n Successfully audited all {len(TARGET_SYMBOLS)} commodity contracts!")
                    return

    except Exception as e:
        print(f"Error inspecting gameloop: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(inspect_gameloop())
