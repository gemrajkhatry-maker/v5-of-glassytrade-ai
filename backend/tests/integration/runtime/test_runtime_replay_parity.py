import pytest

from glassytrade.bootstrap.composition import build_target_runtime, run_target_runtime
from glassytrade.bootstrap.runtime_config import RuntimeConfig


def test_shadow_target_rejects_broker_write_capability(tmp_path):
    config = RuntimeConfig.from_mapping(
        {
            "mode": "shadow",
            "account_id": "shadow-main",
            "exchange": "NSE",
            "database_path": str(tmp_path / "shadow.sqlite3"),
            "evidence_policy": "EXACT_ONLY",
            "risk_policy": {},
            "broker_capabilities": frozenset(),
            "config_fingerprint": "shadow-test",
            "runtime_engine": "target",
        }
    )
    with pytest.raises(ValueError, match="broker-write"):
        build_target_runtime(config, broker=object())


def test_runtime_replay_is_deterministic_for_repeated_tape(tmp_path):
    config = RuntimeConfig.from_mapping(
        {
            "mode": "paper",
            "account_id": "paper-main",
            "exchange": "NSE",
            "database_path": str(tmp_path / "oms.sqlite3"),
            "evidence_policy": "EXACT_ONLY",
            "risk_policy": {},
            "broker_capabilities": frozenset(),
            "config_fingerprint": "runtime-test",
            "runtime_engine": "target",
        }
    )
    tape = (
        {"contract_id": "NIFTY", "price": "100", "sequence": 1},
        {"contract_id": "NIFTY", "price": "101", "sequence": 2},
    )
    first = run_target_runtime(config, tape)
    second = run_target_runtime(config, tape)
    assert first == second
    assert first[-1]["sequence"] == 2
