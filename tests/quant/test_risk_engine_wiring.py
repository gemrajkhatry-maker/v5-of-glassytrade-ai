"""C1 fix — risk persistence must survive restart THROUGH the real wiring.

Regression: the original Task-1 wiring read ``getattr(self._session_levels,
"_storage", None)``, which was always None, so SessionRisk._save/_load were
no-ops in production. The store itself now exposes kv_get/kv_set (backed by
its JSON file); this test exercises the actual QuantEngine wiring, not the
SessionRisk constructor in isolation.
"""

import json
import os
import tempfile

from quant.execution.risk import SessionRisk
from quant.runtime import QuantEngine
from quant.session_levels import SessionLevelStore
from tests.helpers.synthetic import SyntheticGateway


def _store_file():
    fd, path = tempfile.mkstemp(prefix="risk-", suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def test_risk_round_trips_through_engine_store():
    path = _store_file()
    try:
        # Engine 1: one losing trade on a shared file-backed store.
        store = SessionLevelStore(path=path)
        eng = QuantEngine(SyntheticGateway([]), "NIFTY 11 AUG 24600 CALL",
                          interval_seconds=1, market="NSE",
                          session_levels=store)
        # Simulate the runtime's own record path.
        eng._risk.record_trade(-15000.0)
        assert eng._risk.state().daily_pnl == -15000.0

        # Engine 2 (restart) over the SAME file-backed store.
        store2 = SessionLevelStore(path=path)
        eng2 = QuantEngine(SyntheticGateway([]), "NIFTY 11 AUG 24600 CALL",
                           interval_seconds=1, market="NSE",
                           session_levels=store2)
        assert eng2._risk.state().daily_pnl == -15000.0, \
            "risk budget must survive restart through the engine wiring"
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_halt_survives_restart_through_engine():
    path = _store_file()
    try:
        store = SessionLevelStore(path=path)
        eng = QuantEngine(SyntheticGateway([]), "NIFTY 11 AUG 24600 CALL",
                          interval_seconds=1, market="NSE",
                          session_levels=store)
        # 3 consecutive losses -> halt (default max_consecutive_losses=3).
        for _ in range(3):
            eng._risk.record_trade(-1000.0)
        assert eng._risk.state().halted is True

        store2 = SessionLevelStore(path=path)
        eng2 = QuantEngine(SyntheticGateway([]), "NIFTY 11 AUG 24600 CALL",
                           interval_seconds=1, market="NSE",
                           session_levels=store2)
        assert eng2._risk.state().halted is True, \
            "halt must survive restart through the engine wiring"
    finally:
        if os.path.exists(path):
            os.unlink(path)
