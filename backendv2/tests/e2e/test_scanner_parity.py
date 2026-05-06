"""Cross-runtime parity checks for legacy and backendv2 option scanners."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run_scanner_snapshot(runtime_path: Path):
    script = """
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from app.domain.fabio_ai.services.option_scanner import OptionScannerService

@dataclass(frozen=True)
class _Contract:
    symbol: str
    ltp: float
    oi: int
    volume: int
    bid: float
    ask: float
    delta: float = 0.5
    iv: float = 10.0


@dataclass(frozen=True)
class _Chain:
    atm_strike: float
    calls: dict
    puts: dict
    expiry: datetime
    spot_price: float


def chain():
    return _Chain(
        atm_strike=23400.0,
        calls={23400.0: _Contract("NIFTY 20 MAR 23400 CE", 120.0, 200000, 12000, 119.8, 120.2)},
        puts={23400.0: _Contract("NIFTY 20 MAR 23400 PE", 118.0, 180000, 10000, 117.8, 118.2)},
        expiry=datetime.now(tz=timezone.utc) + timedelta(days=7),
        spot_price=23400.0,
    )


class Broker:
    def get_option_chain(self, underlying, exchange="NFO", expiry_index=0):
        return chain()


scanner = OptionScannerService(Broker(), default_underlyings=["NIFTY"])
scan_results = scanner.scan_top_n(n=2, underlyings=["NIFTY"], exchange="NFO", expiry_index=0, strikes_around_atm=1)
print(
    json.dumps(
        [
            {"symbol": r.symbol, "underlying": r.underlying, "score": r.score}
            for r in scan_results
        ]
    )
)
"""

    env = os.environ.copy()
    env["PYTHONPATH"] = str(runtime_path)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    output = proc.stdout.strip().splitlines()
    payload = output[-1] if output else ""
    return json.loads(payload)


def _run_guard_snapshot(runtime_path: Path):
    script = """
from app.domain.fabio_ai.services.option_scanner import ContractSwitchGuard

guard = ContractSwitchGuard()
events = []
events.append(guard.should_switch("NIFTY 20 MAR 23400 CE", 80.0, 0.0))
events.append(guard.should_switch("BANKNIFTY 20 MAR 10000 CE", 95.0, 100.0))
events.append(guard.should_switch("BANKNIFTY 20 MAR 10000 CE", 112.0, 450.0))
guard.set_open_trade(True)
events.append(guard.should_switch("FINNIFTY 20 MAR 23000 CE", 140.0, 500.0))
guard.set_open_trade(False)
events.append(guard.should_switch("FINNIFTY 20 MAR 23000 CE", 200.0, 900.0))
print(json.dumps(events + [guard.current_contract]))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(runtime_path)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    output = proc.stdout.strip().splitlines()
    payload = output[-1] if output else "[]"
    data = json.loads(payload)
    return data[:-1], data[-1]


def test_scanner_snapshot_parity():
    legacy = _run_scanner_snapshot(ROOT / "backend")
    fresh = _run_scanner_snapshot(ROOT / "backendv2")
    assert [item["underlying"] for item in legacy] == [item["underlying"] for item in fresh]
    assert len(legacy) == len(fresh)
    for lhs, rhs in zip(legacy, fresh):
        assert lhs["symbol"] == rhs["symbol"]


def test_contract_switch_guard_parity():
    legacy_events, legacy_contract = _run_guard_snapshot(ROOT / "backend")
    fresh_events, fresh_contract = _run_guard_snapshot(ROOT / "backendv2")
    assert legacy_events == fresh_events
    assert legacy_contract == fresh_contract
