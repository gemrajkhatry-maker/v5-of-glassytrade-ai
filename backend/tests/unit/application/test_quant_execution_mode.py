"""Unit tests for the ``QUANT_EXECUTION_MODE`` gate (off|shadow|paper|live).

Covers:
- SettingsAdapter resolution: env > feature_flags.yaml > back-compat
  ``QUANT_DECISION_ENABLED`` alias (true -> shadow) > default ``off``.
- QuantBridge: decisions computed only when mode != ``off``.
- SessionEventRouter._try_execute_quant_decision: ``off`` -> False,
  ``shadow`` -> True (legacy skipped) without executing, ``paper``/``live``
  route the mapped domain signal to EntryCoordinator.execute_signal.
"""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.services.quant_bridge import QuantBridge
from app.application.services.session_event_router import SessionEventRouter
from app.application.services.session_state_manager import SessionState
from app.config import settings
from app.config_models.settings_adapter import SettingsAdapter
from quant.contracts.entities import Signal as DomainSignal
from quant.contracts.enums import SignalType
from quant.contracts.value_objects import OHLC


def _ohlc(time="t1", close=100.0, high=101.0, low=99.0, open_=100.0, vol=100.0):
    return OHLC.create(
        time=time, open=open_, high=high, low=low, close=close, volume=vol,
        taker_buy_volume=60.0, delta=20.0,
    )


def _aggression_long_ohlc():
    """Deterministic AGGRESSION-LONG session (same trace as the system e2e)."""
    out = []
    for i in range(55):
        out.append(OHLC.create(f"t{i}", 100, 101, 99, 100, 100, 0, 60, 20))
    out.append(OHLC.create("t55", 100, 100, 100, 100, 500, 0, 450, 400))
    for i in range(56, 59):
        out.append(OHLC.create(f"t{i}", 100, 101, 99, 100, 100, 0, 60, 20))
    out.append(OHLC.create("t59", 103.5, 105, 103, 104, 100, 0, 60, 20))
    return out


_LONG_FACTS = {
    "agent_direction": "LONG",
    "agent_probability": 0.7,
    "session_open": True,
    "warmup_complete": True,
    "position_open": False,
    "cooldown_remaining_sec": 0,
    "risk_halted": False,
    "tick_size": 0.5,
}


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
            get_tick_size=lambda s: 0.5,
            max_distance_to_level_ticks=3.0,
        ),
        exchange="MCX",
        allow_short=True,
        gate_tracker=None,
        signal_tracker=None,
        scalp_enabled=False,
    )


# ── SettingsAdapter.QUANT_EXECUTION_MODE resolution ─────────────────────────


def _clear_explicit_mode(monkeypatch):
    """Drop the env var and the yaml key so only the alias/default can apply."""
    monkeypatch.delenv("QUANT_EXECUTION_MODE", raising=False)
    monkeypatch.setattr(SettingsAdapter, "_feature_flags_yaml", lambda self: {})


def test_mode_resolution_default_off(monkeypatch):
    _clear_explicit_mode(monkeypatch)
    monkeypatch.setattr(SettingsAdapter, "QUANT_DECISION_ENABLED", False)
    assert settings.QUANT_EXECUTION_MODE == "off"


def test_mode_resolution_env_overrides_yaml(monkeypatch):
    monkeypatch.setenv("QUANT_EXECUTION_MODE", "paper")
    monkeypatch.setattr(
        SettingsAdapter, "_feature_flags_yaml",
        lambda self: {"quant_execution_mode": "live"},
    )
    assert settings.QUANT_EXECUTION_MODE == "paper"


def test_mode_resolution_yaml_used_when_env_unset(monkeypatch):
    monkeypatch.delenv("QUANT_EXECUTION_MODE", raising=False)
    monkeypatch.setattr(
        SettingsAdapter, "_feature_flags_yaml",
        lambda self: {"quant_execution_mode": "live"},
    )
    assert settings.QUANT_EXECUTION_MODE == "live"


def test_mode_resolution_legacy_flag_true_maps_to_shadow(monkeypatch):
    _clear_explicit_mode(monkeypatch)
    monkeypatch.setattr(SettingsAdapter, "QUANT_DECISION_ENABLED", True)
    assert settings.QUANT_EXECUTION_MODE == "shadow"


def test_mode_resolution_legacy_flag_false_maps_to_off(monkeypatch):
    _clear_explicit_mode(monkeypatch)
    monkeypatch.setattr(SettingsAdapter, "QUANT_DECISION_ENABLED", False)
    assert settings.QUANT_EXECUTION_MODE == "off"


# ── QuantBridge decision compute gate ────────────────────────────────────────


@pytest.mark.parametrize("mode", ["shadow", "paper", "live"])
def test_bridge_computes_decision_when_mode_not_off(monkeypatch, mode):
    monkeypatch.setattr(SettingsAdapter, "QUANT_EXECUTION_MODE", mode)
    br = QuantBridge()
    session = SessionState(symbol="SYM")
    last = {}
    for bar in _aggression_long_ohlc():
        last = br.on_bar_close_with_decision("SYM", bar, session, _LONG_FACTS)
    assert last["tripleAPhase"] == "AGGRESSION"
    assert session.last_quant_decision is not None
    assert session.last_quant_decision["approved"] is True
    assert session.last_quant_decision["signal"]["type"] == "LONG"


def test_bridge_skips_decision_when_mode_off(monkeypatch):
    monkeypatch.setattr(SettingsAdapter, "QUANT_EXECUTION_MODE", "off")
    br = QuantBridge()
    session = SessionState(symbol="SYM")
    last = {}
    for bar in _aggression_long_ohlc():
        last = br.on_bar_close_with_decision("SYM", bar, session, _LONG_FACTS)
    assert last["tripleAPhase"] == "AGGRESSION"
    assert session.last_quant_decision is None  # off -> legacy path untouched


# ── SessionEventRouter routing per mode ──────────────────────────────────────


def test_router_off_never_executes(monkeypatch):
    monkeypatch.setattr(SettingsAdapter, "QUANT_EXECUTION_MODE", "off")
    entry_coordinator = Mock()
    router = _build_router(entry_coordinator, Mock())
    session = SessionState(symbol="SYM")
    session.last_quant_decision = _approved_long_decision()

    assert router._try_execute_quant_decision("SYM", session) is False
    entry_coordinator.execute_signal.assert_not_called()


def test_router_shadow_logs_but_does_not_execute(monkeypatch, caplog):
    monkeypatch.setattr(SettingsAdapter, "QUANT_EXECUTION_MODE", "shadow")
    entry_coordinator = Mock()
    router = _build_router(entry_coordinator, Mock())
    session = SessionState(symbol="SYM")
    session.last_quant_decision = _approved_long_decision()

    with caplog.at_level(
        logging.INFO, logger="app.application.services.session_event_router"
    ):
        executed = router._try_execute_quant_decision("SYM", session)

    assert executed is True  # legacy path skipped, matching flag-on behavior
    entry_coordinator.execute_signal.assert_not_called()
    assert any("SHADOW quant execution would execute" in r.message for r in caplog.records)


@pytest.mark.parametrize("mode", ["paper", "live"])
def test_router_paper_and_live_route_to_execute_signal(monkeypatch, mode):
    monkeypatch.setattr(SettingsAdapter, "QUANT_EXECUTION_MODE", mode)
    entry_coordinator = Mock()
    router = _build_router(entry_coordinator, Mock())
    session = SessionState(symbol="SYM")
    session.last_quant_decision = _approved_long_decision()

    assert router._try_execute_quant_decision("SYM", session) is True
    entry_coordinator.execute_signal.assert_called_once()
    symbol, signal, sess = entry_coordinator.execute_signal.call_args.args
    assert symbol == "SYM"
    assert sess is session
    assert isinstance(signal, DomainSignal)
    assert signal.type == SignalType.BUY  # mapper: LONG -> BUY
    assert float(signal.price) == pytest.approx(104.0)
    assert float(signal.stop_loss) == pytest.approx(100.0)
    assert float(signal.take_profit) == pytest.approx(112.0)
    assert signal.metadata["quant_rr"] == pytest.approx(2.0)
