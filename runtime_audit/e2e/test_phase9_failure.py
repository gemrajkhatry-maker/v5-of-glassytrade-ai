"""PHASE 9 — failure injection against the REAL running backend.

1. Transport disconnect/reconnect (abrupt socket kill, reconnect < 5s,
   fresh full snapshot after resubscribe).
2. Backend restart: SIGTERM behavior (documented actual), graceful shutdown
   evidence in logs, restart, contracts reloaded from .active_contracts.json.
3. Partial/corrupt payloads: malformed JSON, >1MB frame, unknown symbol,
   empty message — record actual close-vs-keep-open behavior.
4. Duplicate/out-of-order events: determinism probe at engine level
   (two fresh engines, same tick sequence, identical traces).
5. Multi-symbol concurrent updates: 3 connections/threads, no cross-symbol bleed.
6. Zombie orders: post-restart positions/trades/journal reconciliation (paper).
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_helper import (  # noqa: E402
    BACKEND_LOG,
    CONTRACTS_FILE,
    ResultTable,
    active_symbols,
    drain,
    http_get,
    recv_json,
    start_backend,
    stop_backend,
    ws_connect,
)

OUT = Path(__file__).resolve().parents[1] / "out"
REPO = Path(__file__).resolve().parents[2]
_RESTARTED_PROC: list = []


def log_tail(n: int = 200) -> str:
    try:
        return BACKEND_LOG.read_text(errors="replace")[-n * 200:]
    except OSError:
        return ""


def case1_reconnect(t: ResultTable) -> None:
    syms = active_symbols()
    sym = syms[0]
    ws = ws_connect(subscribe=sym)
    mode = recv_json(ws, timeout=10)
    first_fulls = [recv_json(ws, timeout=5) for _ in range(3)]
    t.add("9.1a initial subscribe works",
          bool(mode and mode.get("status") == "server_mode"),
          f"symbol={mode.get('symbol') if mode else None}")

    # Abrupt transport kill: SO_LINGER(0) -> RST, no close handshake
    import socket as _socket
    import struct
    try:
        sock = ws.socket
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_LINGER,
                        struct.pack("ii", 1, 0))
        sock.close()
    except Exception:
        ws.close(code=1006)
    t0 = time.time()
    ws2 = ws_connect(subscribe=sym)
    mode2 = recv_json(ws2, timeout=10)
    dt = time.time() - t0
    full2 = [f for f in (recv_json(ws2, timeout=5) for _ in range(3))
             if f and f.get("_type") == "full"]
    t.add("9.1b reconnect within 5s", dt < 5.0, f"reconnect={dt:.2f}s")
    t.add("9.1c fresh full snapshot after resubscribe",
          bool(mode2 and mode2.get("status") == "server_mode" and full2),
          f"full_count={len(full2)}")
    ws2.close()


def case2_restart(t: ResultTable) -> None:
    orig = CONTRACTS_FILE.read_text() if CONTRACTS_FILE.exists() else ""
    proc = start_backend(timeout=90)
    t.add("9.2a backend healthy before restart", True, f"pid={proc.pid}")

    # SIGTERM: lifespan registers a custom SIGTERM handler via signal.signal()
    # which REPLACES uvicorn's graceful-shutdown handler -> expected finding:
    # process ignores SIGTERM. Record actual behavior.
    import signal
    proc.send_signal(signal.SIGTERM)
    deadline = time.time() + 8
    exited = False
    while time.time() < deadline:
        if proc.poll() is not None:
            exited = True
            break
        time.sleep(0.2)
    t.add("9.2b SIGTERM honored (graceful shutdown)", exited,
          "exited on SIGTERM" if exited else
          "FINDING: SIGTERM ignored — lifespan signal.signal(SIGTERM, "
          "_emergency_flatten) overrides uvicorn's shutdown handler")

    if not exited:
        proc.send_signal(signal.SIGINT)
        ok = False
        deadline = time.time() + 15
        while time.time() < deadline:
            if proc.poll() is not None:
                ok = True
                break
            time.sleep(0.2)
        tail = log_tail(120)
        coord_stopped = "QuantCoordinator stopped" in tail
        t.add("9.2c graceful shutdown on SIGINT + coordinator.stop called",
              ok and coord_stopped,
              f"exit={proc.returncode} coordinator_stop_logged={coord_stopped}")
    else:
        tail = log_tail(120)
        t.add("9.2c graceful shutdown + coordinator.stop called",
              "QuantCoordinator stopped" in tail,
              f"exit={proc.returncode}")

    # Restart & contract persistence reload
    proc2 = start_backend(timeout=90)
    _RESTARTED_PROC.append(proc2)
    r = http_get("/health")
    health = r.json()
    tail = log_tail(400)
    reused = bool(re.search(r"[Rr]eusing persisted contracts", tail))
    persisted_syms = []
    try:
        persisted_syms = json.loads(orig).get("symbols", [])
    except Exception:
        pass
    coord = health.get("checks", {}).get("coordinator", {})
    live_syms = coord.get("symbols", [])
    overlap = sorted(set(persisted_syms) & set(live_syms))
    t.add("9.2d restart: /health ok + contracts reloaded from "
          ".active_contracts.json",
          r.status_code == 200 and reused and len(overlap) >= 1,
          f"status={health.get('status')} reused_log={reused} "
          f"persisted={len(persisted_syms)} live={len(live_syms)} "
          f"overlap={overlap[:3]}")
    return


def _recv_until(ws, pred, timeout=15.0, max_frames=200):
    """Receive frames until pred(frame) or timeout; returns (match, seen)."""
    seen = []
    deadline = time.time() + timeout
    while len(seen) < max_frames and time.time() < deadline:
        f = recv_json(ws, timeout=2.0)
        if f is None:
            continue
        seen.append(f)
        if pred(f):
            return f, seen
    return None, seen


def _payload_cases(t: ResultTable) -> None:
    # NOTE: the >1MB guard and JSON validation live in the PRE-subscribe
    # receive loop of gameloop_ws. After the first subscribe, the handler
    # delegates to _coordinator_listener, which has NO size guard and swallows
    # JSONDecodeError silently (broad except -> return). Both behaviors are
    # recorded below.

    # --- pre-subscribe: oversized >1MB -> error frame, connection KEPT open
    ws = ws_connect()  # NO subscribe yet
    ws.send("x" * 1_048_577)
    resp, _ = _recv_until(ws, lambda f: "error" in f)
    ok_too_big = bool(resp and "Payload too large" in str(resp.get("error", "")))
    # prove still open: a valid subscribe now gets server_mode
    ws.send(json.dumps({"subscribe": active_symbols()[0]}))
    mode = recv_json(ws, timeout=10)
    kept = bool(mode and mode.get("status") == "server_mode")
    t.add("9.3a >1MB frame (pre-subscribe): rejected, KEPT open",
          ok_too_big and kept,
          f"error_frame={str(resp)[:70]} still_subscribable={kept}")
    try:
        ws.close()
    except Exception:
        pass

    # --- pre-subscribe: malformed JSON -> error frame then close 1003
    ws = ws_connect()
    ws.send("this is {{ not json")
    resp2 = recv_json(ws, timeout=10)
    close_code = None
    try:
        while True:
            m = ws.recv(timeout=5)
    except Exception as e:
        rcvd = getattr(e, "rcvd", None)
        close_code = getattr(rcvd, "code", None) if rcvd else None
    t.add("9.3c malformed JSON (pre-subscribe): error frame + close",
          bool(resp2 and "Invalid JSON" in str(resp2.get("error", ""))),
          f"error_frame={str(resp2)[:60]} close_code={close_code} "
          f"(gameloop.py: close(1003))")

    # --- pre-subscribe: empty message -> same Invalid JSON path
    ws = ws_connect()
    ws.send("")
    resp3 = recv_json(ws, timeout=10)
    try:
        while True:
            ws.recv(timeout=5)
    except Exception:
        pass
    t.add("9.3d empty message (pre-subscribe): Invalid JSON + close",
          bool(resp3 and "Invalid JSON" in str(resp3.get("error", ""))),
          f"resp={str(resp3)[:60]}")

    # --- POST-subscribe finding: guards are bypassed, listener dies silently
    ws = ws_connect(subscribe=active_symbols()[0])
    recv_json(ws, timeout=10)  # server_mode
    ws.send("this is {{ not json")
    # if the listener died, pings are never answered
    ws.send(json.dumps({"ping": True}))
    pong = recv_json(ws, timeout=6)
    pong2 = recv_json(ws, timeout=4)
    got_pong = any(f and f.get("type") == "pong" for f in (pong, pong2))
    t.add("9.3e FINDING post-subscribe: malformed frame kills listener "
          "silently (no error frame, socket stays open but deaf)",
          not got_pong,
          f"ping_answered={got_pong} (expected-deaf=True means confirmed)")
    try:
        ws.close()
    except Exception:
        pass

    # --- unknown symbol AFTER subscribe: error+availableSymbols, KEPT open
    ws = ws_connect(subscribe=active_symbols()[0])
    mode = recv_json(ws, timeout=10)
    resolved = mode.get("symbol") if mode else None
    ws.send(json.dumps({"subscribe": "ZZZZZ NOT A SYMBOL"}))
    resp4, seen = _recv_until(
        ws,
        lambda f: ("error" in f and "symbol not found" in str(f.get("error", "")))
        or f.get("status") == "symbol_switched")
    # ACTUAL BEHAVIOR: _resolve_symbol falls back to available[0], so an
    # unknown symbol does NOT error when contracts exist — it silently
    # symbol_switched to the first contract. Error+availableSymbols only
    # fires when the coordinator has zero symbols.
    switched_to = resp4.get("symbol") if resp4 else None
    errored = bool(resp4 and "error" in resp4)
    ws.send(json.dumps({"ping": True}))
    frames = [recv_json(ws, timeout=3) for _ in range(8)]
    still_open = any(f and f.get("type") == "pong" for f in frames)
    behavior = ("error+availableSymbols" if errored
                else f"SILENT FALLBACK -> symbol_switched to {switched_to}")
    t.add("9.3b unknown symbol (post-subscribe): handled per gameloop rules",
          bool(resp4) and still_open
          and (errored or switched_to in known_symbols()),
          f"behavior={behavior} kept_open={still_open}")
    try:
        ws.close()
    except Exception:
        pass


def known_symbols() -> list[str]:
    return active_symbols()


def case4_determinism(t: ResultTable) -> None:
    sys.path.insert(0, str(REPO))
    import logging
    logging.getLogger("quant").setLevel(logging.ERROR)
    from quant.brokers.gateway import Tick
    from quant.runtime import QuantEngine

    def make_ticks():
        out = [Tick(f"t{i}", 99.95 if i % 2 == 0 else 100.05, 10, 6, 4, oi=900)
               for i in range(300)]
        out.append(Tick("t300", 100.0, 500, 450, 50, oi=950))
        for i in range(1, 6):
            out.append(Tick(f"t{300+i}", 100.0, 10, 6, 4, oi=950))
        for i, price in enumerate([100.3, 100.6, 100.9, 101.2]):
            out.append(Tick(f"t{306+i}", price, 10, 6, 4, oi=1000))
        return out

    class G:
        def __init__(self, ticks):
            self._t = ticks
            self._i = 0

        def subscribe(self, sym):
            self._i = 0

        def next_tick(self):
            if self._i >= len(self._t):
                return None
            x = self._t[self._i]
            self._i += 1
            return x

    norm = lambda tr: [re.sub(r"event_id='\d+'|correlation_id='[^']*'", "",
                              repr(e)) for e in tr]
    tr1 = norm(QuantEngine(G(make_ticks()), "DET SYM", interval_seconds=1).run())
    tr2 = norm(QuantEngine(G(make_ticks()), "DET SYM", interval_seconds=1).run())
    same = tr1 == tr2
    t.add("9.4 duplicate replay into two fresh engines -> identical traces",
          same and len(tr1) > 50,
          f"events={len(tr1)}/{len(tr2)} identical={same} "
          f"(mini golden tape; event_id/correlation_id normalized)")


def case5_multisymbol(t: ResultTable) -> None:
    syms = active_symbols()[:3]
    if len(syms) < 3:
        t.add("9.5 multi-symbol concurrent", False,
              f"FAIL-FAST: only {len(syms)} active symbols")
        return
    results: dict[int, list] = {0: [], 1: [], 2: []}
    errors: dict[int, str] = {}

    def worker(i: int) -> None:
        try:
            ws = ws_connect(subscribe=syms[i])
            mode = recv_json(ws, timeout=10)
            resolved = mode.get("symbol") if mode else None
            frames = drain(ws, 8.0)
            results[i] = [(resolved, f) for f in frames]
            ws.close()
        except Exception as e:
            errors[i] = repr(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=30)

    # DESIGN FACT: _coordinator_viewer_loop broadcasts deltas for ALL active
    # symbols to every subscriber (gameloop.py "Broadcast deltas for all
    # active symbols continuously"). So other symbols' frames on one
    # connection are by design. The real invariants:
    #   i)  every data frame's _symbol is a known coordinator symbol
    #   ii) the FIRST full snapshot on each connection is that connection's
    #       resolved subscribed symbol (ordered_symbols puts it first)
    #   iii) no frame ever carries an unknown/foreign symbol key
    known = set(active_symbols())
    bleed = []
    first_full_ok = True
    total = 0
    for i, pairs in results.items():
        resolved = pairs[0][0] if pairs else None
        first_full_seen = False
        for _, f in pairs:
            total += 1
            fsym = f.get("_symbol") or f.get("symbol")
            is_data = f.get("_type") in ("full", "delta") or (
                "_symbol" in f and "_type" not in f)
            if is_data and fsym and fsym not in known:
                bleed.append((i, resolved, fsym))
            if f.get("_type") == "full" and not first_full_seen:
                first_full_seen = True
                if resolved and fsym != resolved:
                    first_full_ok = False
                    bleed.append((i, resolved, f"first_full={fsym}"))
    t.add("9.5 3 concurrent WS connections: symbol isolation invariants hold",
          total > 30 and not bleed and not errors and first_full_ok,
          f"frames={total} violations={bleed[:3]} errors={errors or 'none'} "
          f"(note: all-symbols delta broadcast per connection is by design)")


def case6_zombie_orders(t: ResultTable) -> None:
    endpoints = {
        "stats": "/api/trading/stats",
        "positions_events": "/api/trading/positions/events",
        "journal_trades": "/api/journal/trades",
    }
    payloads = {}
    for name, path in endpoints.items():
        try:
            r = http_get(path)
            payloads[name] = (r.status_code, r.text[:500])
        except Exception as e:
            payloads[name] = (0, repr(e))

    def extract_open(name: str, body: str) -> int:
        try:
            data = json.loads(body.split("\n")[0] if False else body)
        except Exception:
            return -1
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (data.get("positions") or data.get("openPositions")
                     or data.get("trades") or data.get("items") or [])
            if isinstance(items, dict):
                items = list(items.values())
        else:
            items = []
        openish = [
            x for x in items if isinstance(x, dict) and str(
                x.get("status", "")).lower() in ("open", "pending", "working")
        ]
        return len(openish)

    stats_body = payloads["stats"][1]
    open_in_stats = ("open" in stats_body.lower())
    pos_code, pos_body = payloads["positions_events"]
    t.add("9.6 zombie orders: no phantom open orders persist un-reconciled "
          "(paper)",
          payloads["stats"][0] == 200 and pos_code == 200
          and not open_in_stats,
          f"stats={payloads['stats'][0]} positions/events={pos_code} "
          f"'open' in stats body={open_in_stats} "
          f"stats_head={stats_body[:120]}")
    print("\n--- raw endpoint evidence ---")
    for name, (code, body) in payloads.items():
        print(f"{name}: HTTP {code} :: {body[:250]}")


def main() -> int:
    print(f"backend log: {BACKEND_LOG}")
    t = ResultTable("PHASE 9 — failure injection")

    proc = start_backend(timeout=90)
    try:
        case1_reconnect(t)
        _payload_cases(t)
        case4_determinism(t)
        case5_multisymbol(t)
    finally:
        stop_backend(proc)

    case2_restart(t)  # boots its own instances; leaves one running
    try:
        case6_zombie_orders(t)
    finally:
        for p in _RESTARTED_PROC:
            stop_backend(p)
    all_ok = t.print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
