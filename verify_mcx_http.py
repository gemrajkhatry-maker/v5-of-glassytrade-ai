#!/usr/bin/env python
"""Verify WebSocket streaming, option contracts, and historical data via HTTP API."""

import requests
import json
import websocket
import time

BACKEND_URL = "http://localhost:9090"

def verify_config():
    """Verify backend configuration."""
    print("\n" + "="*70)
    print("1. VERIFYING BACKEND CONFIGURATION")
    print("="*70)
    
    try:
        response = requests.get(f"{BACKEND_URL}/api/system/config")
        config = response.json()
        
        print(f"\n✅ Backend config retrieved:")
        print(f"   Exchange: {config.get('exchange', 'N/A')}")
        print(f"   Default Symbol: {config.get('defaultSymbol', 'N/A')}")
        print(f"   Active Symbols: {config.get('activeSymbols', [])}")
        print(f"   Symbols: {config.get('symbols', [])}")
        print(f"   Data Source: {config.get('dataSource', 'N/A')}")
        
        return config
    except Exception as e:
        print(f"\n❌ Failed to get config: {e}")
        return None


def verify_ai_history():
    """Verify AI decision history (indicates system is processing)."""
    print("\n" + "="*70)
    print("2. VERIFYING AI HISTORY")
    print("="*70)
    
    try:
        response = requests.get(f"{BACKEND_URL}/api/ai/history")
        data = response.json()
        
        decisions = data.get('decisions', [])
        print(f"\n✅ AI History endpoint working")
        print(f"   Total decisions: {len(decisions)}")
        
        if decisions:
            print(f"\n   Recent decisions:")
            for i, d in enumerate(decisions[:3], 1):
                print(f"   {i}. Symbol: {d.get('_symbol', 'N/A')}")
                print(f"      Time: {d.get('timestamp', d.get('_time', 'N/A'))}")
                print(f"      Direction: {d.get('direction', d.get('llm_direction', 'N/A'))}")
                print(f"      Confidence: {d.get('confidence', d.get('llm_confidence', 'N/A'))}")
        
        return True
    except Exception as e:
        print(f"\n❌ Failed to get AI history: {e}")
        return False


def verify_websocket_connection():
    """Verify WebSocket connection and data streaming."""
    print("\n" + "="*70)
    print("3. VERIFYING WEBSOCKET STREAMING")
    print("="*70)
    
    received_messages = []
    error_msg = None
    
    def on_message(ws, message):
        data = json.loads(message)
        received_messages.append(data)
        
        msg_type = data.get('_type', data.get('status', 'unknown'))
        symbol = data.get('_symbol', data.get('symbol', 'N/A'))
        
        if msg_type == 'server_mode':
            print(f"\n✅ Connected in server-driven mode")
            print(f"   Active symbols: {data.get('activeSymbols', [])}")
            print(f"   Primary symbol: {data.get('symbol', 'N/A')}")
            print(f"   Exchange: {data.get('exchange', 'N/A')}")
            print(f"   Interval: {data.get('interval', 'N/A')}")
        elif msg_type == 'history_loaded':
            count = data.get('count', 0)
            print(f"\n✅ Historical data loaded for {symbol}: {count} candles")
            if data.get('history'):
                hist = data['history']
                if len(hist) > 0:
                    first = hist[0]
                    last = hist[-1]
                    print(f"   First: {first.get('time', 'N/A')} C={first.get('close', 'N/A')}")
                    print(f"   Last:  {last.get('time', 'N/A')} C={last.get('close', 'N/A')}")
        elif msg_type == 'full':
            print(f"\n✅ Full state received for {symbol}")
            if 'portfolio' in data:
                portfolio = data['portfolio']
                print(f"   Positions: {len(portfolio.get('open_positions', []))}")
                print(f"   Closed trades: {len(portfolio.get('closed_trades', []))}")
            if 'amt' in data:
                amt = data['amt']
                print(f"   Market state: {amt.get('market_state', 'N/A')}")
                print(f"   Aggression sigma: {amt.get('aggression_sigma', 'N/A')}")
        elif msg_type == 'delta':
            print(f"\n✅ Delta update for {symbol} (fields: {len([k for k in data.keys() if not k.startswith('_')])})")
    
    def on_error(ws, error):
        nonlocal error_msg
        error_msg = str(error)
        print(f"\n❌ WebSocket error: {error}")
    
    def on_close(ws, close_status_code, close_msg):
        print(f"\nWebSocket closed: {close_status_code} - {close_msg}")
    
    def on_open(ws):
        print(f"\n✅ WebSocket connection opened")
        # Get config first to know which symbol to subscribe
        config_response = requests.get(f"{BACKEND_URL}/api/system/config")
        config = config_response.json()
        symbols = config.get('activeSymbols', config.get('symbols', []))
        
        if symbols:
            symbol = symbols[0]
            print(f"   Subscribing to: {symbol}")
            ws.send(json.dumps({"subscribe": symbol}))
        else:
            print("   ⚠️  No symbols in config, subscribing to CRUDEOIL")
            ws.send(json.dumps({"subscribe": "CRUDEOIL"}))
    
    try:
        ws = websocket.WebSocketApp(
            f"ws://localhost:9090/api/trading/ws/gameloop",
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        
        # Run for 10 seconds to receive messages
        import threading
        ws_thread = threading.Thread(target=ws.run_forever, daemon=True)
        ws_thread.start()
        
        # Wait for messages
        time.sleep(10)
        ws.close()
        ws_thread.join(timeout=2)
        
        if received_messages:
            print(f"\n✅ Received {len(received_messages)} messages total")
            return True
        else:
            print(f"\n⚠️  No messages received")
            if error_msg:
                print(f"   Error: {error_msg}")
            return False
            
    except Exception as e:
        print(f"\n❌ WebSocket test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all verifications."""
    print("\n" + "="*70)
    print("GLASSYTRADE AI - MCX MODE VERIFICATION (HTTP API)")
    print("="*70)
    print(f"\nBackend URL: {BACKEND_URL}")
    
    # Run verifications
    config = verify_config()
    ai_ok = verify_ai_history()
    ws_ok = verify_websocket_connection()
    
    # Summary
    print("\n" + "="*70)
    print("VERIFICATION SUMMARY")
    print("="*70)
    
    if config:
        symbols = config.get('activeSymbols', config.get('symbols', []))
        exchange = config.get('exchange', 'N/A')
        
        print(f"\n1. Configuration: ✅ PASS")
        print(f"   - Exchange: {exchange}")
        print(f"   - Symbols: {symbols}")
        
        # Check if using options or underlyings
        has_options = any(' ' in s for s in symbols)
        if has_options:
            print(f"   - ✅ Using option contracts")
        else:
            print(f"   - ⚠️  Using underlying symbols (not options)")
    else:
        print(f"\n1. Configuration: ❌ FAIL")
    
    print(f"\n2. AI History: {'✅ PASS' if ai_ok else '⚠️  NO DATA'}")
    print(f"3. WebSocket Streaming: {'✅ PASS' if ws_ok else '❌ FAIL'}")
    
    if config and ws_ok:
        print("\n✅ System is operational in MCX mode")
        print("   WebSocket streaming is working")
        print("   Frontend should be able to connect and receive data")
    else:
        print("\n⚠️  System has issues - check backend logs")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    main()
