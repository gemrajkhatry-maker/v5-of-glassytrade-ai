"""SessionEventRouter routing — quant decision drives execution when the flag is on."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.services.session_event_router import SessionEventRouter
from app.application.services.session_state_manager import SessionState
from app.config_models.settings_adapter import SettingsAdapter
from quant.contracts.entities import Signal as DomainSignal
from quant.contracts.enums import SignalType
from quant.contracts.value_objects import OHLC


def _build_router(entry_coordinator, risk_coordinator):
    return SessionEventRouter(
        lifecycle_handler=Mock(),
        llm_handler=Mock(),
        overseer_handler=Mock(),
        entry_coordinator=entry_coordinator,
        exit_coordinator=Mock(),
        broker=Mock(),
        storage=None,
        risk_coordinator=risk_coordinator,
        probability_engine=Mock(),
        exchange_config=SimpleNamespace(
            get_tick_size=lambda s: 0.05,
            max_distance_to_level_ticks=3.0,
        ),
        exchange="MCX",
        allow_short=True,
        gate_tracker=None,
        signal_tracker=None,
        scalp_enabled=False,
    )


def _risk_manager():
    return SimpleNamespace(
        can_trade=True,
        risk_tier=SimpleNamespace(name="NORMAL"),
        stop_loss_pct=0.01,
        halt_reason=None,
        session_pnl=0.0,
        consecutive_losses=0,
    )


def _approved_long_decision():
    return {
        "approved": True,
        "reason": "Triple-A",
        "phase": "AGGRESSION",
        "timestamp": "t59",
        "signal": {
            "type": "LONG",
            "entry": 104.0,
            "sl": 100.0,
            "tp": 112.0,
            "rr": 2.0,
            "confidence": 0.8,
        },
    }


def _call_execute_entry_path(router, session, entry_coordinator):
    event = SimpleNamespace(
        symbol="SYM",
        data=[],
        tick=OHLC.create(time="t59", open=103.5, high=105, low=103, close=104, volume=100),
        tick_trace_id="trace-1",
    )
    amt_result = SimpleNamespace(
        cvd_slope=0.0,
        aggression=0.5,
        market_state="BALANCED",
    )
    router.execute_entry_path(
        event=event,
        session=session,
        amt_result=amt_result,
        exec_dir="LONG",
        exec_prob=0.7,
        run_entry=True,
        exchange_config=SimpleNamespace(
            get_tick_size=lambda s: 0.05,
            max_distance_to_level_ticks=3.0,
        ),
        allow_short=True,
        scalp_enabled=False,
    )
    return entry_coordinator


def test_router_uses_quant_when_flag_on(monkeypatch):
    monkeypatch.setattr(SettingsAdapter, "QUANT_DECISION_ENABLED", True)
    monkeypatch.setattr(
        "app.application.services.session_event_router.run_gate_pipeline",
        Mock(),
    )
    entry_coordinator = Mock()
    risk_coordinator = Mock()
    risk_coordinator.get_session_risk_manager.return_value = _risk_manager()
    router = _build_router(entry_coordinator, risk_coordinator)

    session = SessionState(symbol="SYM")
    session.last_quant_decision = _approved_long_decision()

    _call_execute_entry_path(router, session, entry_coordinator)

    entry_coordinator.execute_signal.assert_called_once()
    symbol, signal, sess = entry_coordinator.execute_signal.call_args.args
    assert symbol == "SYM"
    assert sess is session
    assert isinstance(signal, DomainSignal)
    assert signal.type == SignalType.BUY  # mapper: LONG -> BUY (no LONG in SignalType)
    assert float(signal.price) == pytest.approx(104.0)
    assert signal.metadata["quant_rr"] == pytest.approx(2.0)
    # Legacy gate path must NOT have run
    from app.application.services import session_event_router as router_mod

    router_mod.run_gate_pipeline.assert_not_called()


def test_router_legacy_path_unchanged_when_flag_off(monkeypatch):
    monkeypatch.setattr(SettingsAdapter, "QUANT_DECISION_ENABLED", False)
    gate_pipeline = Mock(return_value=(False, "GATE_BLOCKED", "test", 0, 0))
    monkeypatch.setattr(
        "app.application.services.session_event_router.run_gate_pipeline",
        gate_pipeline,
    )
    entry_coordinator = Mock()
    risk_coordinator = Mock()
    risk_coordinator.get_session_risk_manager.return_value = _risk_manager()
    router = _build_router(entry_coordinator, risk_coordinator)

    session = SessionState(symbol="SYM")
    session.last_quant_decision = _approved_long_decision()  # present but flag off

    _call_execute_entry_path(router, session, entry_coordinator)

    entry_coordinator.execute_signal.assert_not_called()  # quant ignored
    gate_pipeline.assert_called_once()  # legacy gates ran
