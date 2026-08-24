"""Unit tests for startup contract builder."""

from __future__ import annotations

from typing import Any

from app.application.services.startup_contracts import build_startup_contracts
from app.domain.ops.startup_reconciliation import ReconciliationResult


class _StrategyRouter:
    def execute_entry_path(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def trigger_llm_entry(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def should_trigger_llm(self, *_args: Any, **_kwargs: Any) -> bool:
        return False


class _CloseCoordinator:
    def on_position_closed(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def _resolve_position(self, *_args: Any, **_kwargs: Any):
        return None, ""


class _Broker:
    def get_positions(self):
        return []

    def get_account_positions(self):
        return []

    def execute_order(self, *_args: Any, **_kwargs: Any):
        return None

    def cancel_order(self, *_args: Any, **_kwargs: Any):
        return None


class _Storage:
    def load_open_positions(self):
        return []

    def save_open_position(self, *_args: Any, **_kwargs: Any):
        return None

    def delete_open_position(self, *_args: Any, **_kwargs: Any):
        return None

    def save_trade(self, *_args: Any, **_kwargs: Any):
        return None

    def kv_set(self, *_args: Any, **_kwargs: Any):
        return None


class _TradingSession:
    def __init__(self, with_strategy: bool = True, with_close: bool = True) -> None:
        self._event_router = _StrategyRouter() if with_strategy else None
        self._exit_coordinator = _CloseCoordinator() if with_close else None
        self._broker = _Broker()
        self._storage = _Storage()

    def process_tick(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def test_startup_contracts_healthy_state(monkeypatch) -> None:
    # Note: settings.* are read-only env/YAML-backed properties on
    # SettingsAdapter and cannot be monkeypatched. YAML defaults provide
    # SCANNER_TOP_N>0 and DEFAULT_EXCHANGE="MCX", so this is unnecessary.

    session = _TradingSession()
    contract = build_startup_contracts(
        trading_session=session,
        active_symbols=["NIFTY", "BANKNIFTY"],
        reconciliation_result=ReconciliationResult(
            db_positions=1,
            broker_positions=1,
            restored=0,
            stale_removed=0,
            orphaned_registered=0,
            discrepancies=[],
        ),
    )

    assert contract.status == "ok"
    assert contract.checks["strategy_runtime"] == "ok"
    assert contract.checks["position_close_contract"] == "ok"
    assert contract.checks["broker_runtime"] == "ok"
    assert contract.checks["storage_runtime"] == "ok"
    assert contract.checks["reconciliation"] == "ok"


def test_startup_contracts_broker_runtime_must_define_execute_and_cancel(monkeypatch) -> None:
    # Note: settings.* are read-only env/YAML-backed properties on
    # SettingsAdapter and cannot be monkeypatched. YAML defaults provide
    # SCANNER_TOP_N>0 and DEFAULT_EXCHANGE="MCX", so this is unnecessary.

    class _BadBroker(_Broker):
        execute_order = None

    session = _TradingSession()
    session._broker = _BadBroker()
    contract = build_startup_contracts(
        trading_session=session,
        active_symbols=["NIFTY"],
        reconciliation_result=ReconciliationResult(
            db_positions=0,
            broker_positions=0,
            restored=0,
            stale_removed=0,
            orphaned_registered=0,
            discrepancies=[],
        ),
    )
    assert contract.checks["broker_runtime"].startswith("error")


def test_startup_contracts_storage_runtime_requires_persistence_methods(monkeypatch) -> None:
    # Note: settings.* are read-only env/YAML-backed properties on
    # SettingsAdapter and cannot be monkeypatched. YAML defaults provide
    # SCANNER_TOP_N>0 and DEFAULT_EXCHANGE="MCX", so this is unnecessary.

    class _BadStorage(_Storage):
        save_trade = None

    session = _TradingSession()
    session._storage = _BadStorage()
    contract = build_startup_contracts(
        trading_session=session,
        active_symbols=["NIFTY"],
        reconciliation_result=ReconciliationResult(
            db_positions=0,
            broker_positions=0,
            restored=0,
            stale_removed=0,
            orphaned_registered=0,
            discrepancies=[],
        ),
    )
    assert contract.checks["storage_runtime"].startswith("error")


def test_startup_contracts_strategy_runtime_uses_callability(monkeypatch) -> None:
    # Note: settings.* are read-only env/YAML-backed properties on
    # SettingsAdapter and cannot be monkeypatched. YAML defaults provide
    # SCANNER_TOP_N>0 and DEFAULT_EXCHANGE="MCX", so this is unnecessary.

    session = _TradingSession(with_strategy=False)
    contract = build_startup_contracts(
        trading_session=session,
        active_symbols=["NIFTY"],
        reconciliation_result=ReconciliationResult(
            db_positions=0,
            broker_positions=0,
            restored=0,
            stale_removed=0,
            orphaned_registered=0,
            discrepancies=[],
        ),
    )
    assert contract.checks["strategy_runtime"].startswith("error")


def test_startup_contracts_reconciliation_depends_on_storage_and_broker_methods(monkeypatch) -> None:
    # Note: settings.* are read-only env/YAML-backed properties on
    # SettingsAdapter and cannot be monkeypatched. YAML defaults provide
    # SCANNER_TOP_N>0 and DEFAULT_EXCHANGE="MCX", so this is unnecessary.

    class _BadStorage(_Storage):
        load_open_positions = None

    session = _TradingSession()
    session._storage = _BadStorage()
    contract = build_startup_contracts(
        trading_session=session,
        active_symbols=["NIFTY"],
        reconciliation_result=ReconciliationResult(
            db_positions=0,
            broker_positions=0,
            restored=0,
            stale_removed=0,
            orphaned_registered=0,
            discrepancies=[],
        ),
    )
    assert contract.checks["reconciliation"].startswith("error")


def test_startup_contracts_reconciliation_execution_failure() -> None:
    session = _TradingSession()
    contract = build_startup_contracts(
        trading_session=session,
        active_symbols=["NIFTY"],
        reconciliation_result=ReconciliationResult(
            db_positions=0,
            broker_positions=0,
            restored=0,
            stale_removed=0,
            orphaned_registered=0,
            discrepancies=[],
        ),
        reconciliation_executed=False,
    )
    assert contract.checks["reconciliation"] == "error: reconciliation not executed"
    assert contract.status == "degraded"
