"""Unit tests for _build_startup_contracts runtime probes."""

import pytest
from app.main import _build_startup_contracts


class MockBrokerValid:
    def execute_order(self, *args, **kwargs): pass
    def cancel_order(self, *args, **kwargs): pass
    def close_position(self, *args, **kwargs): pass


class MockBrokerMissingClose:
    def execute_order(self, *args, **kwargs): pass


class MockCoordinatorValid:
    def emergency_halt(self, *args, **kwargs): return 1
    def force_close_position(self, *args, **kwargs): return True


class MockCoordinatorMissingHalt:
    pass


class MockStorageValid:
    def save_open_position(self, *args, **kwargs): pass
    def delete_open_position(self, *args, **kwargs): pass
    def save_trade(self, *args, **kwargs): pass
    def kv_set(self, *args, **kwargs): pass


def test_startup_contracts_all_valid():
    contracts = _build_startup_contracts(
        broker=MockBrokerValid(),
        storage=MockStorageValid(),
        active_symbols=["CRUDEOIL SEP FUT", "NATURALGAS SEP FUT"],
        coordinator=MockCoordinatorValid(),
        engine_start_failed=False,
        reconciliation_executed=True,
    )
    assert contracts["strategy_runtime"] == "ok"
    assert contracts["position_close_contract"] == "ok"
    assert contracts["status"] == "ok"


def test_startup_contracts_engine_start_failed():
    contracts = _build_startup_contracts(
        broker=MockBrokerValid(),
        storage=MockStorageValid(),
        active_symbols=["CRUDEOIL SEP FUT"],
        coordinator=MockCoordinatorValid(),
        engine_start_failed=True,
        reconciliation_executed=True,
    )
    assert contracts["strategy_runtime"].startswith("error:")
    assert contracts["status"] == "degraded"


def test_startup_contracts_missing_position_close():
    contracts = _build_startup_contracts(
        broker=MockBrokerMissingClose(),
        storage=MockStorageValid(),
        active_symbols=["CRUDEOIL SEP FUT"],
        coordinator=MockCoordinatorMissingHalt(),
        engine_start_failed=False,
        reconciliation_executed=True,
    )
    assert contracts["position_close_contract"].startswith("error:")
    assert contracts["status"] == "degraded"
