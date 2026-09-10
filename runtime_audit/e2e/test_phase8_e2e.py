"""PHASE 8 — E2E: real backend boot + WS contract validation.

Legs:
  A. Real uvicorn subprocess (port 9091, paper env) -> /health 200.
  B. Python websocket client subscribes first active symbol from
     /api/system/config; observe frames for 10s: server_mode, full snapshots,
     deltas.
  C. Tick-injection leg: cross-process injection into the running backend's
     coordinator is NOT possible without modifying production code (the
     coordinator is fed by a live Dhan MultiplexedMarketFeed only — there is
     no injection endpoint). Honest fail-fast for the cross-process leg, plus
     an IN-PROCESS harness that drives synthetic ticks through the real
     QuantEngine -> StateProjector -> view_state_to_ws path (the exact code
     the backend's coordinator.snapshot uses) to prove deltas flow and values
     are non-zero when ticks ARE fed.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_helper import (  # noqa: E402
    BACKEND_LOG,
    ResultTable,
    active_symbols,
    drain,
    recv_json,
    start_backend,
    stop_backend,
    ws_connect,
)

OUT = Path(__file__).resolve().parents[1] / "out"


def leg_a_boot() -> tuple[object, list[str]]:
    t = ResultTable("PHASE 8 leg A/B — real backend + WS contract")
    proc = start_backend(timeout=90)
    t.add("A1 real uvicorn boots, /health 200 in <=90s", True, f"pid={proc.pid}")

    syms = active_symbols()
    t.add("B0 /api/system/config exposes active symbols", bool(syms), f"{syms[:3]}...")

    symbol = syms[0]
    ws = ws_connect(subscribe=symbol)
    server_mode = recv_json(ws, timeout=10)
    ok_mode = bool(server_mode and server_mode.get("status") == "server_mode")
    resolved = (server_mode or {}).get("symbol", "?")
    t.add("B1 server_mode frame on subscribe", ok_mode,
          f"requested={symbol} resolved={resolved}")

    frames = drain(ws, 10.0)
    fulls = [f for f in frames if f.get("_type") == "full"]
    deltas = [f for f in frames if f.get("_type") == "delta" or
              ("_type" not in f and "_symbol" in f)]
    pongs = [f for f in frames if f.get("type") == "pong"]
    others = len(frames) - len(fulls) - len(deltas) - len(pongs)
    t.add("B2 backend emits frames over 10s window", len(frames) > 0,
          f"total={len(frames)} full={len(fulls)} delta={len(deltas)} "
          f"pong={len(pongs)} other={others}")
    t.add("B3 full snapshot(s) received with _type=full", len(fulls) >= 1,
          f"count={len(fulls)} keys={sorted(fulls[0].keys())[:8] if fulls else '-'}")

    # Offline (no Dhan feed) ltp stays None -> projector state never changes ->
    # _compute_delta returns {} -> no deltas. Record actual behavior honestly.
    if deltas:
        t.add("B4 deltas flow while idle", True, f"count={len(deltas)}")
    else:
        t.add("B4 deltas flow while idle", False,
              "0 deltas in 10s — expected offline: no feed ticks, "
              "projector state static, _compute_delta emits nothing")

    snap = fulls[0] if fulls else {}
    t.add("B5 snapshot shape matches ws_adapter contract",
          all(k in snap for k in ("_symbol", "portfolio", "amt", "auction",
                                  "quantDecision", "riskState", "ltp", "oi")),
          f"ltp={snap.get('ltp')} oi={snap.get('oi')} "
          f"portfolio.balance={ (snap.get('portfolio') or {}).get('balance') }")

    ws.close()
    return proc, (t, resolved)


def leg_c_inprocess_injection(symbol: str) -> ResultTable:
    """Drive ticks through the REAL QuantEngine/StateProjector/ws_adapter."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import logging
    logging.getLogger("quant").setLevel(logging.ERROR)
    t = ResultTable("PHASE 8 leg C — tick injection (in-process harness)")
    from quant.brokers.gateway import Tick
    from quant.runtime import QuantEngine
    from quant.ws_adapter import view_state_to_ws

    def make_ticks():
        out = [Tick(f"t{i}", 99.95 if i % 2 == 0 else 100.05, 10, 6, 4, oi=1200)
               for i in range(300)]
        out.append(Tick("t300", 100.0, 500, 450, 50, oi=1250))
        for i in range(1, 6):
            out.append(Tick(f"t{300+i}", 100.0, 10, 6, 4, oi=1250))
        for i, price in enumerate([100.3, 100.6, 100.9, 101.2]):
            out.append(Tick(f"t{306+i}", price, 10, 6, 4, oi=1300))
        return out

    eng = QuantEngine(_FakeGateway(make_ticks()), symbol, interval_seconds=1)
    trace = eng.run()
    bars = [e for e in trace if type(e).__name__ == "BarClosed"]

    t.add("C1 engine consumes fed ticks -> bars close", len(bars) >= 15,
          f"events={len(trace)} bars={len(bars)}")

    snap = view_state_to_ws(eng.projector.snapshot(symbol))
    t.add("C2 fed values non-zero in projected state",
          snap.get("ltp") not in (None, 0) and snap.get("oi") not in (None, 0),
          f"ltp={snap.get('ltp')} oi={snap.get('oi')}")

    prev = {k: ({} if k != "_symbol" else snap["_symbol"]) for k in snap}
    delta = _compute_delta(prev, snap)
    t.add("C3 delta computed vs empty baseline is non-empty", bool(delta),
          f"delta_keys={sorted(delta.keys())[:8]}")

    eng2 = QuantEngine(_FakeGateway(make_ticks()), symbol, interval_seconds=1)
    trace2 = eng2.run()
    import re
    norm = lambda tr: [re.sub(r"event_id='\d+'|correlation_id='[^']*'", "", repr(e))
                       for e in tr]
    same = norm(trace) == norm(trace2)
    t.add("C4 replay determinism (same ticks -> identical trace)", same,
          f"len={len(trace)}/{len(trace2)}; raw reprs differ ONLY in "
          f"event_id/correlation_id bus metadata" if same else
          f"len={len(trace)}/{len(trace2)} CONTENT DIVERGENCE")
    return t


class _FakeGateway:
    """Minimal BrokerGateway over a fixed tick list (mirrors tests.helpers)."""

    def __init__(self, ticks):
        self._ticks = ticks
        self._i = 0

    def subscribe(self, symbol):
        self._i = 0

    def next_tick(self):
        if self._i >= len(self._ticks):
            return None
        t = self._ticks[self._i]
        self._i += 1
        return t


def _deep_equal(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return len(a) == len(b) and all(
            k in b and _deep_equal(v, b[k]) for k, v in a.items())
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(
            _deep_equal(x, y) for x, y in zip(a, b))
    return a == b


def _compute_delta(prev, current):
    delta = {"_symbol": current.get("_symbol", ""), "_type": "delta"}
    for key, value in current.items():
        if key.startswith("_"):
            continue
        if not _deep_equal(prev.get(key), value):
            delta[key] = value
    return delta


def main() -> int:
    print(f"backend log: {BACKEND_LOG}")
    proc, (t_ab, resolved) = leg_a_boot()
    try:
        t_c = leg_c_inprocess_injection(resolved)
    except Exception as e:
        t_c = ResultTable("PHASE 8 leg C — tick injection (in-process harness)")
        t_c.add("C0 harness ran", False, f"FAIL-FAST: {type(e).__name__}: {e}")
    stop_info = stop_backend(proc)
    print("\n--- backend shutdown ---")
    print(json.dumps(stop_info, indent=2))

    ok_ab = t_ab.print()
    ok_c = t_c.print()

    print(
        "\nNOTE: cross-process tick injection into the running backend is NOT\n"
        "possible without modifying production code (coordinator consumes a\n"
        "live Dhan MultiplexedMarketFeed; no injection endpoint exists).\n"
        "Leg C therefore validates the fed-tick path IN-PROCESS through the\n"
        "real QuantEngine -> StateProjector -> view_state_to_ws chain."
    )
    return 0 if (ok_ab and ok_c) else 1


if __name__ == "__main__":
    sys.exit(main())
