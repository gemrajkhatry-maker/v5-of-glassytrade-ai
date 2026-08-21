"""PHASE 1 — real bootstrap validation (paper mode, TestClient lifespan)."""

import logging

import pytest


@pytest.fixture(scope="module")
def client():
    import signal as _signal

    _orig = _signal.signal

    def _thread_safe_signal(signum, handler):
        import threading
        if threading.current_thread() is not threading.main_thread():
            print(f"\n[FINDING] signal.signal({signum}) skipped off-main-thread "
                  f"under TestClient — production registers SIGTERM in lifespan "
                  f"(backend/app/main.py:276); uvicorn path unaffected")
            return lambda *a: None
        return _orig(signum, handler)

    _signal.signal = _thread_safe_signal
    try:
        import os
        os.environ["GLASSYTRADE_ENV"] = "paper"
        from fastapi.testclient import TestClient
        from backend.app.main import create_application

        records: list[logging.LogRecord] = []

        class _Cap(logging.Handler):
            def emit(self, record):
                records.append(record)

        cap = _Cap()
        logging.getLogger().addHandler(cap)
        with TestClient(create_application()) as c:
            yield c, records
        logging.getLogger().removeHandler(cap)
    finally:
        _signal.signal = _orig


def test_boot_health(client):
    c, records = client
    r = c.get("/health")
    assert r.status_code == 200, f"boot failed: {r.text[:300]}"
    body = r.json()
    print("\n/health:", str(body)[:200])


def test_readiness(client):
    c, _ = client
    r = c.get("/health/ready")
    print("/health/ready:", r.status_code, str(r.json())[:200])
    assert r.status_code == 200


def test_system_config(client):
    c, _ = client
    r = c.get("/api/system/config")
    assert r.status_code == 200
    body = r.json()
    for field in ("activeSymbols", "defaultSymbol"):
        assert field in body, f"config missing {field}: {list(body)}"
    print("/api/system/config:", str(body)[:250])


def test_startup_telemetry_captured(client):
    _, records = client
    msgs = [r.getMessage() for r in records]
    boot_logs = [m for m in msgs if "startup" in m.lower() or "coordinator" in m.lower()]
    print(f"\nstartup-related log records: {len(boot_logs)}")
    for m in boot_logs[:5]:
        print("  ", m[:150])
    assert records, "no log records captured during lifespan"
