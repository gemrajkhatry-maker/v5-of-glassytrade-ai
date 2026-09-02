"""Leg A — cross-process E2E: HTTP injection → live engine → WS boundary."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime_audit" / "e2e"))

try:
    from boot_helper import (  # noqa: E402
        active_symbols,
        start_backend,
        stop_backend,
        ws_connect,
    )
    HAVE_BOOT = True
except Exception:  # websockets missing etc.
    HAVE_BOOT = False

BASE = "http://127.0.0.1:9093"
WS = "ws://127.0.0.1:9093/api/trading/ws/gameloop"
T0 = 1_787_664_600  # in-session MCX evening anchor


def _is_trading_day() -> bool:
    """Leg A boots the real app whose coordinator only scans/spawns on NSE/MCX
    trading days — on weekends/holidays it starts with zero symbols and the
    chain can never engage. Skip honestly instead of failing environmentally."""
    try:
        from quant.contracts.market_calendar import is_trading_day

        return is_trading_day()
    except Exception:
        return True  # calendar unavailable: let the test try anyway


def _packet(epoch: int, price: float, vol: float, buy_frac: float) -> dict:
    return {
        "symbol": "GOLDM SEP FUT",
        "ltp": price,
        "open": price,
        "high": price + 0.01,
        "low": price - 0.01,
        "close": price,
        "volume": vol,
        "total_buy_qty": vol * buy_frac,
        "total_sell_qty": vol * (1 - buy_frac),
        "timestamp": str(epoch),
        "symbol_tick_time": str(epoch),
    }


@pytest.mark.skipif(not HAVE_BOOT, reason="boot_helper deps unavailable")
@pytest.mark.skipif(
    not _is_trading_day(), reason="coordinator spawns no engines on non-trading days"
)
@pytest.mark.e2e
def test_leg_a_full_chain_http_to_ws():
    import os
    import subprocess
    import urllib.request

    repo = Path(__file__).resolve().parents[2]
    py = repo / ".venv" / "bin" / "python"
    py = py if py.exists() else Path(sys.executable)
    env = dict(os.environ)
    env["GLASSYTRADE_ENV"] = "development"
    env["PYTHONPATH"] = f"{repo / 'backend'}:{repo}"
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    logf = open(repo / "backend" / "backend_e2e.log", "ab")
    proc = subprocess.Popen(
        [str(py), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", "9093"],
        cwd=str(repo / "backend"), env=env, stdout=logf, stderr=logf,
    )
    try:
        # wait for health (generous: uvicorn boot under a loaded machine)
        deadline = time.time() + 120
        up = False
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{BASE}/api/health", timeout=3) as r:
                    if r.status == 200:
                        up = True
                        break
            except Exception:
                time.sleep(1.0)
        assert up, "backend did not become healthy in 120s"

        # Coordinator scan hits real Dhan endpoints, which throttle under
        # repeated boots (and contend with a running live app) — so symbols
        # may legitimately lag health. Poll instead of asserting immediately.
        deadline = time.time() + 120
        symbols: list = []
        while time.time() < deadline:
            try:
                health = json.loads(
                    urllib.request.urlopen(f"{BASE}/api/health", timeout=5).read()
                )
                symbols = (
                    health.get("checks", {}).get("coordinator", {}).get("symbols")
                ) or []
                if symbols:
                    break
            except Exception:
                pass
            time.sleep(2.0)
        assert symbols, (
            f"no active symbols in health after 120s: "
            f"{list((health or {}).get('checks', {}))[:8]}"
        )
        # Inject into a FUTURES symbol whose ticks aggregate to bars; options
        # have thin synthetic volume. Prefer the futures contract of GOLDM.
        symbol = next((s for s in symbols if s.startswith("GOLDM")), symbols[0])

        # Inject into the FIRST active symbol (sorted) so the WS subscription
        # observes it. Prices chosen at MCX-futures scale.
        story = []
        sec = T0 + int(time.time() % 60)
        base_px = 25000.0
        for i in range(30):
            story.append(_packet(sec, base_px + 0.5 * ((i % 4) - 1.5), 8.0, 0.5))
            sec += 1
        price = base_px + 0.5
        for i in range(20):
            price += 2.0
            story.append(_packet(sec, price, 30.0, 0.85))
            sec += 1

        req = urllib.request.Request(
            f"{BASE}/api/inject-tick",
            data=json.dumps(story).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
        assert body["injected"] == len(story), f"injection partial: {body}"

        # Observation window: only extended for FAILURE paths — the loop still
        # breaks early on success, so green runs cost the same as before.
        deadline = time.time() + 60
        amts_seen, above_mid = 0, False
        from websockets.sync.client import connect as ws_connect_9093
        ws = ws_connect_9093(WS, open_timeout=10, close_timeout=3)
        ws.send(json.dumps({"subscribe": symbol}))
        frame_log = []
        try:
            while time.time() < deadline:
                try:
                    raw = ws.recv(timeout=10)  # full snapshot sweep takes a beat
                except TimeoutError:
                    continue  # keep polling until overall deadline
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                frame_log.append((msg.get("_type"), msg.get("_symbol"),
                                  str(msg.get("ltp"))[:8]))
                if msg.get("_symbol") != symbol:
                    continue
                if float(msg.get("ltp") or 0) > base_px + 0.5:
                    above_mid = True
                if msg.get("_type") == "full" and msg.get("amt"):
                    amts_seen += 1
                if amts_seen >= 3 and above_mid:
                    break
        finally:
            ws.close()

        # Diagnostics on failure
        print(f"\n[diag] frames={frame_log[:8]} amts={amts_seen} above={above_mid}")
        assert above_mid or amts_seen >= 1, (
            "injected displacement never reached the WS boundary"
        )
    finally:
        if not os.environ.get("E2E_KEEP"):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


def test_leg_a_guard_rejects_non_dev_env(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routers.testing import router as testing_router

    app = FastAPI()
    app.include_router(testing_router, prefix="/api")
    app.state.coordinator = None
    client = TestClient(app)

    # Paper is blocked; synthetic feed injection is development-only.
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    r = client.post("/api/inject-tick", json=[{"symbol": "S"}])
    assert r.status_code == 403

    monkeypatch.setenv("GLASSYTRADE_ENV", "development")
    monkeypatch.delenv("TRADING_MODE", raising=False)
    r2 = client.post("/api/inject-tick", json=[{"symbol": "S"}])
    assert r2.status_code == 503

    # LIVE mode must stay blocked — injection is a paper/dev validation tool.
    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    monkeypatch.setenv("TRADING_MODE", "live")
    r3 = client.post("/api/inject-tick", json=[{"symbol": "S"}])
    assert r3.status_code == 403
