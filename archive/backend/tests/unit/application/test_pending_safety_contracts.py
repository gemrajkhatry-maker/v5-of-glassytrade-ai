from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from app.application.services.startup_contracts import build_startup_contracts
from app.application.services.session_event_logger import SessionEventLogger


class _Broker:
    def execute_order(self, *_args, **_kwargs):
        return None

    def cancel_order(self, *_args, **_kwargs):
        return True

    def get_positions(self):
        return []


class _Storage:
    def save_open_position(self, *_args, **_kwargs):
        return None

    def delete_open_position(self, *_args, **_kwargs):
        return None

    def save_trade(self, *_args, **_kwargs):
        return None

    def kv_set(self, *_args, **_kwargs):
        return None

    def load_open_positions(self):
        return []


class _Router:
    def execute_entry_path(self, *_args, **_kwargs):
        return None

    def trigger_llm_entry(self, *_args, **_kwargs):
        return None

    def should_trigger_llm(self, *_args, **_kwargs):
        return False


class _Exit:
    def on_position_closed(self, *_args, **_kwargs):
        return None

    def _resolve_position(self, *_args, **_kwargs):
        return None, ""


def _session(fallback):
    return SimpleNamespace(
        _storage=_Storage(),
        _broker=_Broker(),
        _event_router=_Router(),
        _exit_coordinator=_Exit(),
        _db_fallback=fallback,
        process_tick=lambda *_args, **_kwargs: None,
    )


def test_legacy_mock_fallback_does_not_fake_degraded_persistence():
    contracts = build_startup_contracts(
        trading_session=_session(Mock()),
        active_symbols=["NIFTY"],
        reconciliation_result=SimpleNamespace(
            db_positions=0,
            broker_positions=0,
            restored=0,
            stale_removed=0,
            orphaned_registered=0,
            discrepancies=[],
        ),
        reconciliation_executed=True,
    )
    assert contracts.checks["persistence_durability"] == "ok"


def test_degraded_persistence_fails_startup_contract():
    fallback = SimpleNamespace(durability_degraded=True)
    contracts = build_startup_contracts(
        trading_session=_session(fallback),
        active_symbols=["NIFTY"],
        reconciliation_result=SimpleNamespace(
            db_positions=0,
            broker_positions=0,
            restored=0,
            stale_removed=0,
            orphaned_registered=0,
            discrepancies=[],
        ),
        reconciliation_executed=True,
    )
    assert contracts.checks["persistence_durability"].startswith("error")
    assert contracts.status == "degraded"


def test_position_event_metadata_uses_canonical_source_field():
    saved: list[dict] = []
    logger = object.__new__(SessionEventLogger)
    logger._storage = SimpleNamespace(save_position_event=saved.append)

    common = {
        "position_id": "P1",
        "symbol": "NIFTY 26 AUG 25000 CALL",
        "session_id": "session-1",
        "sequence": 7,
        "correlation_id": "tick-7",
        "causation_id": "event-6",
        "source": "quant",
    }
    logger.log_position_event(event_type="OPENED", event_time="t1", **common)
    logger.log_position_event(
        event_type="CLOSED",
        event_time="t2",
        event_id="close-1",
        **common,
    )

    assert len(saved) == 2
    assert saved[0]["source"] == "quant"
    assert saved[1]["event_id"] == "close-1"
    assert all(event["session_id"] == "session-1" for event in saved)
    assert all(event["correlation_id"] == "tick-7" for event in saved)
    assert all(event["causation_id"] == "event-6" for event in saved)
    assert all("event_source" not in event for event in saved)
