"""Phase 4 — transport-layer runtime validation against the REAL app.

Boots backend.app.main under starlette TestClient (lifespan ON,
GLASSYTRADE_ENV=paper), opens /api/trading/ws/gameloop, subscribes to a live
coordinator contract, captures ~6s of raw inbound JSON frames verbatim to
runtime_audit/out/ws_frames.jsonl, and validates:

  - config frame field parity with frontend/hooks/useServerTradingSystem.ts
  - snapshot frame required keys + symbol/timestamp contracts
  - ltp/volume assertions gated on real tick flow (SKIPPED-OFFLINE otherwise)
  - delta frames keys within the known snapshot key set
  - REST /api/system/config and /api/market/history/NIFTY
  - JSON serialization sanity (no NaN/Infinity in raw text)
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

os.environ["GLASSYTRADE_ENV"] = "paper"

OUT_DIR = Path(__file__).resolve().parents[1] / "out"
FRAMES_PATH = OUT_DIR / "ws_frames.jsonl"

WS_PATH = "/api/trading/ws/gameloop"
CAPTURE_SECONDS = 6.0

# Known top-level snapshot key set — quant/ws_adapter.view_state_to_ws plus
# transport markers added by gameloop.py (_type) and delta compression.
SNAPSHOT_KEYS = {
    "_symbol",
    "_type",
    "portfolio",
    "amt",
    "auction",
    "quantDecision",
    "agentDecision",
    "riskState",
    "tick",
    "ltp",
    "oi",
    "depth",
}

# Frontend parity — extracted from frontend/hooks/useServerTradingSystem.ts:
#   L200-204 (applyConfig): cfg.backendPort, cfg.activeSymbols, cfg.defaultSymbol
#   L357-387 (server_mode): state.activeSymbols, state.symbol, state.interval
SERVER_MODE_REQUIRED_FIELDS = ["status", "symbol", "activeSymbols", "interval"]
SYSTEM_CONFIG_REQUIRED_FIELDS = ["backendPort", "activeSymbols", "defaultSymbol"]

NAN_INF_RE = re.compile(r"(?<![\"\w])(NaN|-?Infinity)(?![\"\w])")

_BOOT: dict = {"error": None}


@pytest.fixture(scope="module")
def app_client():
    """Boot the REAL FastAPI app with lifespan ON. Fail-fast on boot error."""
    # FINDING (documented harness shim, no production change): backend/app/main.py:276
    # installs a SIGTERM handler inside lifespan startup via signal.signal(), which
    # raises "ValueError: signal only works in main thread" under starlette TestClient
    # (lifespan runs in a worker thread). Shim degrades to a no-op off-main-thread so
    # transport validation can boot the real app.
    import signal as _signal

    _orig_signal = _signal.signal

    def _thread_safe_signal(signum, handler):
        try:
            return _orig_signal(signum, handler)
        except ValueError as e:
            if "main thread" in str(e):
                print(f"\n[FINDING] signal.signal({signum}) skipped off-main-thread "
                      f"(backend/app/main.py:276) — SIGTERM emergency-flatten inactive "
                      f"under TestClient")
                return None
            raise

    _signal.signal = _thread_safe_signal

    try:
        from fastapi.testclient import TestClient
        from app.main import app as fastapi_app
    except Exception as e:  # pragma: no cover
        pytest.exit(
            f"PHASE FAILED: boot\nREASON: could not import/build the real app\n"
            f"MISSING: importable backend.app.main\nBLOCKING PATH: "
            f"runtime_audit/transport/test_phase4_transport.py -> app.main -> {type(e).__name__}: {e}",
            returncode=1,
        )
    try:
        with TestClient(fastapi_app) as client:
            coordinator = getattr(fastapi_app.state, "coordinator", None)
            yield client, fastapi_app, coordinator
    except Exception as e:
        _BOOT["error"] = e
        pytest.exit(
            f"PHASE FAILED: boot\nREASON: real app failed to boot under "
            f"GLASSYTRADE_ENV=paper (credentials/network/lifespan)\nMISSING: "
            f"healthy app lifespan\nBLOCKING PATH: TestClient lifespan startup -> "
            f"{type(e).__name__}: {e}",
            returncode=1,
        )


def test_boot_real_app(app_client):
    client, fastapi_app, coordinator = app_client
    assert _BOOT["error"] is None, f"boot raised: {_BOOT['error']}"
    assert coordinator is not None, (
        "PHASE FAILED: boot\nREASON: app.state.coordinator missing after lifespan\n"
        "MISSING: QuantCoordinator on app.state\n"
        "BLOCKING PATH: main.lifespan -> container.resolve(QuantCoordinator) -> start()"
    )
    syms = coordinator.symbols()
    print(f"\n[boot] coordinator symbols: {syms}")


def test_ws_capture_and_frame_contracts(app_client):
    client, fastapi_app, coordinator = app_client

    available = []
    if coordinator is not None:
        try:
            available = list(coordinator.symbols() or [])
        except Exception:
            available = []

    # Subscribe contract discovered from live coordinator; fallback NIFTY.
    requested = available[0] if available else "NIFTY"
    if not available:
        print("\n[subscribe] no live coordinator contracts — falling back to 'NIFTY'")

    raw_frames: list[str] = []
    stop = threading.Event()
    errors: list[str] = []

    with client.websocket_connect(WS_PATH) as ws:
        ws.send_text(json.dumps({"subscribe": requested}))

        def receiver():
            while not stop.is_set():
                try:
                    raw_frames.append(ws.receive_text())
                except Exception as e:  # session closed / stopped
                    if not stop.is_set():
                        errors.append(f"{type(e).__name__}: {e}")
                    break

        def pinger():
            # Keep traffic alive so the capture window ends even when the
            # offline stream goes silent (no deltas without tick data).
            while not stop.wait(1.0):
                try:
                    ws.send_text(json.dumps({"ping": True}))
                except Exception:
                    break

        threads = [
            threading.Thread(target=receiver, daemon=True),
            threading.Thread(target=pinger, daemon=True),
        ]
        for t in threads:
            t.start()
        time.sleep(CAPTURE_SECONDS)
        stop.set()
        try:
            ws.close()
        except Exception:
            pass
        for t in threads:
            t.join(timeout=3)

    # ---- persist every inbound frame VERBATIM ----
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FRAMES_PATH.write_text("\n".join(raw_frames) + ("\n" if raw_frames else ""), encoding="utf-8")
    print(f"\n[capture] {len(raw_frames)} raw frames -> {FRAMES_PATH}")
    assert raw_frames, (
        f"PHASE FAILED: ws-capture\nREASON: zero inbound frames in {CAPTURE_SECONDS}s "
        f"(subscribed '{requested}')\nMISSING: any server frame on {WS_PATH}\n"
        f"BLOCKING PATH: gameloop_ws -> _coordinator_viewer_loop -> server_mode send"
    )

    parsed: list[dict] = []
    bad_json: list[str] = []
    for i, raw in enumerate(raw_frames):
        try:
            parsed.append(json.loads(raw))
        except json.JSONDecodeError as e:
            bad_json.append(f"frame#{i}: {e}")
    assert not bad_json, f"non-JSON inbound frames: {bad_json[:3]}"

    # ---- serialization sanity: no NaN/Infinity anywhere in raw text ----
    nan_hits = [i for i, raw in enumerate(raw_frames) if NAN_INF_RE.search(raw)]
    assert not nan_hits, f"NaN/Infinity leaked in raw frames at indices {nan_hits[:5]}"
    for frame in parsed:
        json.dumps(frame, allow_nan=False)  # raises on NaN/Inf floats

    config_frames = [f for f in parsed if f.get("status") == "server_mode"]
    full_frames = [f for f in parsed if f.get("_type") == "full"]
    delta_frames = [f for f in parsed if f.get("_type") == "delta"]
    pong_frames = [f for f in parsed if f.get("type") == "pong"]
    print(f"[frames] server_mode={len(config_frames)} full={len(full_frames)} "
          f"delta={len(delta_frames)} pong={len(pong_frames)} other={len(parsed) - len(config_frames) - len(full_frames) - len(delta_frames) - len(pong_frames)}")

    # ---- config frame frontend parity ----
    assert config_frames, (
        "PHASE FAILED: ws-config\nREASON: no server_mode config frame received\n"
        "MISSING: {'status':'server_mode',...} first frame\n"
        "BLOCKING PATH: _coordinator_viewer_loop step 1 -> settings.DEFAULT_EXCHANGE/STREAM_INTERVAL"
    )
    cfg = config_frames[0]
    missing_cfg = [k for k in SERVER_MODE_REQUIRED_FIELDS if k not in cfg]
    assert not missing_cfg, (
        f"PHASE FAILED: frontend-parity(config)\nREASON: server_mode frame missing fields "
        f"the frontend reads (useServerTradingSystem.ts L357-387)\n"
        f"MISSING: {missing_cfg}\nBLOCKING PATH: gameloop.py server_mode payload -> "
        f"useServerTradingSystem.ts state.status==='server_mode' handler"
    )
    assert isinstance(cfg["activeSymbols"], list) and cfg["activeSymbols"], \
        "server_mode.activeSymbols must be a non-empty list (frontend purges all instruments otherwise)"
    live_contracts = list(cfg["activeSymbols"])

    # ---- snapshot frames ----
    assert full_frames, (
        "PHASE FAILED: ws-snapshot\nREASON: no '_type':'full' snapshot frames received\n"
        "MISSING: full snapshots after server_mode\n"
        "BLOCKING PATH: _coordinator_viewer_loop step 2 -> coordinator.snapshot(s)"
    )
    problems: list[str] = []
    seen_symbols: set[str] = set()
    for i, snap in enumerate(full_frames):
        for key in ("_symbol", "_type"):
            if key not in snap:
                problems.append(f"frame#{i}: missing required key '{key}'")
        if not any(k in snap for k in ("amt", "auction", "ltp", "tick")):
            problems.append(f"frame#{i}: none of amt/auction/ltp/tick present")
        sym = snap.get("_symbol")
        if sym:
            seen_symbols.add(sym)
            if live_contracts and sym not in live_contracts:
                problems.append(f"frame#{i}: _symbol '{sym}' not in activeSymbols {live_contracts}")
        tick = snap.get("tick")
        if isinstance(tick, dict) and tick.get("time"):
            try:
                datetime.fromisoformat(str(tick["time"]))
            except ValueError:
                problems.append(f"frame#{i}: tick.time not ISO-parseable: {tick['time']!r}")
    assert not problems, f"snapshot contract violations:\n" + "\n".join(problems[:10])
    print(f"[snapshots] symbols streamed: {sorted(seen_symbols)}")

    # ---- ltp/volume non-zero ONLY if tick data actually flowed ----
    ltp_values = [s.get("ltp") for s in full_frames]
    volumes = [s["tick"]["volume"] for s in full_frames
               if isinstance(s.get("tick"), dict) and s["tick"].get("volume") is not None]
    ticks_flowed = any(v is not None and v > 0 for v in ltp_values) or any(v > 0 for v in volumes)
    if ticks_flowed:
        zero_ltp = [v for v in ltp_values if v is not None and v <= 0]
        zero_vol = [v for v in volumes if v <= 0]
        assert not zero_ltp, f"tick data flowed but non-positive ltp present: {zero_ltp[:5]}"
        assert not zero_vol, f"tick data flowed but zero volume present: {zero_vol[:5]}"
        print(f"[feed] LIVE tick data: ltp sample={ltp_values[0]}, volume sample={volumes[0]}")
    else:
        print(
            "\nSKIPPED-OFFLINE: ltp/volume positivity checks\n"
            f"REASON: no market feed in this environment (offline/paper boot); "
            f"all snapshot ltp={set(map(str, ltp_values))} with no positive tick volume\n"
            "NOT FAKE-PASSED: assertion skipped with reason, not asserted true"
        )

    # ---- delta frames: keys within known snapshot key set ----
    unknown: list[tuple[int, list[str]]] = []
    for i, d in enumerate(delta_frames):
        extra = sorted(set(d.keys()) - SNAPSHOT_KEYS)
        if extra:
            unknown.append((i, extra))
    assert not unknown, f"delta frames carry unknown keys: {unknown[:5]}"
    if delta_frames:
        print(f"[deltas] {len(delta_frames)} delta frames, all keys within known set")


def test_rest_system_config(app_client):
    client, _, _ = app_client
    resp = client.get("/api/system/config")
    assert resp.status_code == 200, (
        f"PHASE FAILED: rest-config\nREASON: GET /api/system/config returned "
        f"{resp.status_code}\nMISSING: 200 response\n"
        f"BLOCKING PATH: health.py system_config -> get_configuration/settings"
    )
    body = resp.json()
    missing = [k for k in SYSTEM_CONFIG_REQUIRED_FIELDS if k not in body]
    assert not missing, (
        f"PHASE FAILED: frontend-parity(rest-config)\nREASON: /api/system/config missing "
        f"fields the frontend reads (useServerTradingSystem.ts L200-204)\n"
        f"MISSING: {missing}\nBLOCKING PATH: health.py system_config -> applyConfig()"
    )
    print(f"\n[rest] /api/system/config 200: defaultSymbol={body.get('defaultSymbol')!r} "
          f"activeSymbols={body.get('activeSymbols')} backendPort={body.get('backendPort')} "
          f"env={os.environ.get('GLASSYTRADE_ENV')}")


def test_rest_market_history(app_client):
    client, _, _ = app_client
    resp = client.get("/api/market/history/NIFTY", params={"interval": "1m", "limit": 50})
    print(f"\n[rest] /api/market/history/NIFTY -> {resp.status_code}")
    if resp.status_code >= 500:
        body = resp.text[:300]
        pytest.fail(
            f"PHASE FAILED: rest-history\nREASON: GET /api/market/history/NIFTY returned "
            f"{resp.status_code} (offline should degrade gracefully, not 5xx)\n"
            f"MISSING: graceful empty/4xx history response\n"
            f"BLOCKING PATH: market.py get_history -> market_data.fetch_history -> {body}"
        )
