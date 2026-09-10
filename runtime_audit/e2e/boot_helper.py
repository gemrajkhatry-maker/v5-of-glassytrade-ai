"""Shared boot helper for runtime_audit E2E phases.

Starts the REAL uvicorn backend as a subprocess (port 9091, paper env),
waits for /health 200, and provides a sync WebSocket client helper built on
the installed `websockets` package (v17 sync client).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "runtime_audit" / "out"
BACKEND_LOG = OUT_DIR / "e2e_backend.log"
PORT = 9091
BASE = f"http://127.0.0.1:{PORT}"
WS_URL = f"ws://127.0.0.1:{PORT}/api/trading/ws/gameloop"
PY = REPO / ".venv" / "bin" / "python"

CONTRACTS_FILE = REPO / "backend" / ".active_contracts.json"


def start_backend(timeout: float = 90.0) -> subprocess.Popen:
    """Boot real uvicorn; block until /health returns 200 (any status body)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["GLASSYTRADE_ENV"] = "paper"
    env["PYTHONPATH"] = f"{REPO / 'backend'}:{REPO}"
    env.pop("HTTP_PROXY", None)
    env.pop("HTTPS_PROXY", None)
    logf = open(BACKEND_LOG, "ab")
    proc = subprocess.Popen(
        [
            str(PY), "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(PORT),
            "--log-level", "info",
        ],
        cwd=str(REPO / "backend"),
        stdout=logf,
        stderr=subprocess.STDOUT,
        env=env,
    )
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        rc = proc.poll()
        if rc is not None:
            raise RuntimeError(f"backend exited early rc={rc}; see {BACKEND_LOG}")
        try:
            r = httpx.get(f"{BASE}/health", timeout=2.0)
            if r.status_code == 200:
                return proc
            last_err = f"/health -> {r.status_code}"
        except Exception as e:
            last_err = repr(e)
        time.sleep(0.5)
    stop_backend(proc)
    raise RuntimeError(f"backend not healthy in {timeout}s (last: {last_err})")


def wait_gone(proc: subprocess.Popen, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.1)
    return False


def stop_backend(proc: subprocess.Popen) -> dict:
    """SIGTERM -> SIGINT -> SIGKILL escalation; records actual behavior."""
    info: dict = {"sigterm_exited": False, "exit_code": None, "escalation": []}
    if proc.poll() is not None:
        info["exit_code"] = proc.returncode
        return info
    try:
        proc.send_signal(signal.SIGTERM)
    except ProcessLookupError:
        pass
    if wait_gone(proc, 8):
        info["sigterm_exited"] = True
        info["exit_code"] = proc.returncode
        return info
    info["escalation"].append("SIGTERM ignored (still alive after 8s)")
    try:
        proc.send_signal(signal.SIGINT)
    except ProcessLookupError:
        pass
    if wait_gone(proc, 10):
        info["exit_code"] = proc.returncode
        info["escalation"].append("exited after SIGINT")
        return info
    info["escalation"].append("SIGINT ignored (still alive after 10s)")
    try:
        proc.send_signal(signal.SIGKILL)
    except ProcessLookupError:
        pass
    wait_gone(proc, 5)
    info["exit_code"] = proc.returncode
    info["escalation"].append("SIGKILL used")
    return info


def http_get(path: str, timeout: float = 10.0) -> httpx.Response:
    return httpx.get(f"{BASE}{path}", timeout=timeout)


def ws_connect(subscribe: str | None = None, *, open_timeout: float = 10.0):
    """Open a sync WS connection; optionally send subscribe immediately."""
    from websockets.sync.client import connect

    ws = connect(WS_URL, open_timeout=open_timeout, close_timeout=3)
    if subscribe is not None:
        ws.send(json.dumps({"subscribe": subscribe}))
    return ws


def recv_json(ws, timeout: float = 5.0) -> dict | None:
    try:
        raw = ws.recv(timeout=timeout)
    except TimeoutError:
        return None
    except Exception:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return {"_raw": str(raw)[:200]}


def drain(ws, seconds: float) -> list[dict]:
    out = []
    deadline = time.time() + seconds
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        msg = recv_json(ws, timeout=min(remaining, 1.0))
        if msg is not None:
            out.append(msg)
    return out


def active_symbols() -> list[str]:
    r = http_get("/api/system/config")
    r.raise_for_status()
    cfg = r.json()
    syms = [s for s in (cfg.get("activeSymbols") or []) if s]
    return syms or [cfg.get("defaultSymbol")]


class ResultTable:
    def __init__(self, title: str) -> None:
        self.title = title
        self.rows: list[tuple[str, str, str]] = []

    def add(self, criterion: str, passed: bool, evidence: str) -> None:
        self.rows.append((criterion, "PASS" if passed else "FAIL", evidence))

    def print(self) -> bool:
        print(f"\n=== {self.title}: pass/fail criteria ===")
        w = max(len(r[0]) for r in self.rows) + 2
        all_ok = True
        for name, status, ev in self.rows:
            print(f"{name.ljust(w)} {status}  {ev}")
            all_ok &= status == "PASS"
        print(f"OVERALL: {'PASS' if all_ok else 'FAIL'}")
        return all_ok


if __name__ == "__main__":
    p = start_backend()
    print("backend healthy, pid", p.pid)
    stop_backend(p)
