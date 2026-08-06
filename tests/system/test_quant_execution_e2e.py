"""System E2E: quant decision drives EntryCoordinator.execute_signal per mode.

Feeds the 60-bar synthetic AGGRESSION-LONG session through QuantBridge with
QUANT_EXECUTION_MODE paper/live, then routes the stored quant decision via
SessionEventRouter._try_execute_quant_decision and asserts the (mocked)
EntryCoordinator received a domain BUY Signal whose entry/stop/take-profit
match the quant Signal exactly. Also proves the mode ``off`` path never touches
the entry coordinator and that ``shadow`` computes + broadcasts but never
executes.
"""

import pathlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.application.services.quant_bridge import QuantBridge
from app.application.services.session_event_router import SessionEventRouter
from app.application.services.session_state_manager import SessionState
from app.config import settings
from app.config_models.settings_adapter import SettingsAdapter
from quant.contracts.entities import Signal as DomainSignal
from quant.contracts.enums import SignalType
from quant.contracts.value_objects import OHLC

SYMBOL = "SYM"


def _session_ohlc():
    """60-bar synthetic session reaching AGGRESSION/LONG on the final bar.

    Quiet bars @100 vol 100 -> t55 absorption spike (500 vol, 450 buys, tight
    range) -> near-POC accumulation -> t59 breakout close 104 -> AGGRESSION.
    Deterministic: the committed ws_session_long.json fixture asserts this
    exact trace (see tests/system/test_quant_system_e2e.py).
    """
    out = []
    for i in range(55):
        out.append(OHLC.create(f"t{i}", 100, 101, 99, 100, 100, 0, 60, 20))
    out.append(OHLC.create("t55", 100, 100, 100, 100, 500, 0, 450, 400))
    for i in range(56, 59):
        out.append(OHLC.create(f"t{i}", 100, 101, 99, 100, 100, 0, 60, 20))
    out.append(OHLC.create("t59", 103.5, 105, 103, 104, 100, 0, 60, 20))
    return out


def _ctx_facts():
    return {
        "agent_direction": "LONG",
        "agent_probability": 0.7,
        # Gate-5 caps stop distance at 20 ticks; the quant SL sits ~4.5 below
        # entry, so a coarse 0.5 tick is required (per Task 3's finding).
        "tick_size": 0.5,
        "symbol": SYMBOL,
    }


def _feed_session(bridge, session):
    """Feed all 60 bars through the bridge's decision path; return last DTO."""
    last = {}
    for ohlc in _session_ohlc():
        last = bridge.on_bar_close_with_decision(SYMBOL, ohlc, session, _ctx_facts())
    return last


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


def test_quant_decision_drives_execution_when_mode_paper(monkeypatch):
    monkeypatch.setattr(SettingsAdapter, "QUANT_EXECUTION_MODE", "paper")
    bridge = QuantBridge()
    session = SessionState(symbol=SYMBOL)

    _feed_session(bridge, session)

    # After the breakout bar the quant decision must be an approved LONG.
    decision = session.last_quant_decision
    assert decision is not None
    assert decision["approved"] is True
    assert decision["reason"] == "Triple-A"
    assert decision["phase"] == "AGGRESSION"
    assert decision["signal"]["type"] == "LONG"

    entry_coordinator = Mock()
    router = _build_router(entry_coordinator, Mock())
    executed = router._try_execute_quant_decision(SYMBOL, session)

    assert executed is True
    entry_coordinator.execute_signal.assert_called_once()
    symbol, signal, sess = entry_coordinator.execute_signal.call_args.args
    assert symbol == SYMBOL
    assert sess is session
    assert isinstance(signal, DomainSignal)
    assert signal.type == SignalType.BUY  # mapper: LONG -> BUY (SignalType has no LONG)
    assert float(signal.price) == pytest.approx(decision["signal"]["entry"])
    assert float(signal.stop_loss) == pytest.approx(decision["signal"]["sl"])
    assert float(signal.take_profit) == pytest.approx(decision["signal"]["tp"])
    assert signal.metadata["quant_rr"] == pytest.approx(decision["signal"]["rr"])


def test_quant_decision_live_shares_paper_code_path(monkeypatch):
    monkeypatch.setattr(SettingsAdapter, "QUANT_EXECUTION_MODE", "live")
    bridge = QuantBridge()
    session = SessionState(symbol=SYMBOL)

    _feed_session(bridge, session)
    assert session.last_quant_decision is not None
    assert session.last_quant_decision["approved"] is True

    entry_coordinator = Mock()
    router = _build_router(entry_coordinator, Mock())
    assert router._try_execute_quant_decision(SYMBOL, session) is True
    entry_coordinator.execute_signal.assert_called_once()


def test_quant_decision_shadow_computes_but_never_executes(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(SettingsAdapter, "QUANT_EXECUTION_MODE", "shadow")
    bridge = QuantBridge()
    session = SessionState(symbol=SYMBOL)

    _feed_session(bridge, session)

    # Shadow computes + stores the decision (broadcastable as quantDecision)...
    assert session.last_quant_decision is not None
    assert session.last_quant_decision["approved"] is True

    entry_coordinator = Mock()
    router = _build_router(entry_coordinator, Mock())
    with caplog.at_level(
        logging.INFO, logger="app.application.services.session_event_router"
    ):
        executed = router._try_execute_quant_decision(SYMBOL, session)

    # ...but the entry coordinator is never touched; legacy path still skipped.
    assert executed is True
    entry_coordinator.execute_signal.assert_not_called()
    assert any("SHADOW quant execution would execute" in r.message for r in caplog.records)


def test_quant_decision_ignored_when_mode_off(monkeypatch):
    monkeypatch.setattr(SettingsAdapter, "QUANT_EXECUTION_MODE", "off")
    bridge = QuantBridge()
    session = SessionState(symbol=SYMBOL)

    _feed_session(bridge, session)

    # Mode off -> bridge stores nothing; the legacy path stays byte-identical.
    assert session.last_quant_decision is None

    # Even a stale approved decision is ignored by the router when the mode is off.
    session.last_quant_decision = {
        "approved": True,
        "reason": "Triple-A",
        "phase": "AGGRESSION",
        "timestamp": "t59",
        "signal": {
            "type": "LONG",
            "entry": 104.0,
            "sl": 99.54,
            "tp": 112.92,
            "rr": 2.0,
            "confidence": 1.0,
        },
    }
    entry_coordinator = Mock()
    router = _build_router(entry_coordinator, Mock())
    executed = router._try_execute_quant_decision(SYMBOL, session)

    assert executed is False
    entry_coordinator.execute_signal.assert_not_called()


def test_quant_decision_legacy_flag_true_without_explicit_mode_is_shadow(monkeypatch, caplog):
    """Back-compat: QUANT_DECISION_ENABLED=true (no mode set) behaves as shadow."""
    import logging

    monkeypatch.delenv("QUANT_EXECUTION_MODE", raising=False)
    monkeypatch.setattr(SettingsAdapter, "_feature_flags_yaml", lambda self: {})
    monkeypatch.setattr(SettingsAdapter, "QUANT_DECISION_ENABLED", True)

    assert settings.QUANT_EXECUTION_MODE == "shadow"

    bridge = QuantBridge()
    session = SessionState(symbol=SYMBOL)
    _feed_session(bridge, session)
    assert session.last_quant_decision is not None
    assert session.last_quant_decision["approved"] is True

    entry_coordinator = Mock()
    router = _build_router(entry_coordinator, Mock())
    with caplog.at_level(
        logging.INFO, logger="app.application.services.session_event_router"
    ):
        executed = router._try_execute_quant_decision(SYMBOL, session)

    assert executed is True
    entry_coordinator.execute_signal.assert_not_called()
    assert any("SHADOW quant execution would execute" in r.message for r in caplog.records)
