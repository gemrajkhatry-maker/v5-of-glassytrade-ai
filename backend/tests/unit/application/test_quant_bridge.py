"""Unit tests for the quant→backend bridge + AuctionState serializer."""

import pytest

from app.application.services.quant_bridge import (
    QuantBridge,
    auction_state_to_dto,
    ohlc_to_quant_bar,
    quant_decision_to_dto,
)
from app.application.services.session_state_manager import SessionState
from app.config_models.settings_adapter import SettingsAdapter
from quant.contracts.value_objects import OHLC


def _ohlc(time="t1", close=100.0, high=101.0, low=99.0, open_=100.0, vol=100.0):
    return OHLC.create(
        time=time, open=open_, high=high, low=low, close=close, volume=vol,
        taker_buy_volume=60.0, delta=20.0,
    )


def test_ohlc_to_quant_bar_maps_fields():
    b = ohlc_to_quant_bar(_ohlc())
    assert b.time == "t1"
    assert b.close == 100.0
    assert b.high == 101.0
    assert b.low == 99.0
    assert b.buy_volume == 60.0
    assert b.sell_volume == pytest.approx(40.0)
    assert b.delta == 20.0


def test_bridge_returns_serialized_auction():
    br = QuantBridge()
    dto = br.on_bar_close("SYM", _ohlc())
    assert dto
    assert dto["tripleAPhase"] in ("WAITING", "ABSORBING", "ACCUMULATING", "AGGRESSION")
    assert "volumeProfile" in dto and dto["volumeProfile"]["poc"] > 0
    assert "vwap" in dto and "location" in dto and "orderFlow" in dto


def test_bridge_dedups_same_bar_time():
    br = QuantBridge()
    br.on_bar_close("SYM", _ohlc(time="t1"))
    assert br.on_bar_close("SYM", _ohlc(time="t1")) == {}  # duplicate -> no-op
    assert br.on_bar_close("SYM", _ohlc(time="t2")) != {}  # new bar -> new state


def test_bridge_reset():
    br = QuantBridge()
    br.on_bar_close("SYM", _ohlc(time="t1"))
    br.reset("SYM")
    assert br.on_bar_close("SYM", _ohlc(time="t1")) != {}  # fresh coordinator


def test_auction_state_to_dto_camel_case_keys():
    br = QuantBridge()
    dto = br.on_bar_close("SYM", _ohlc(vol=500, close=100.2))
    assert "tripleASignal" in dto
    assert "deviationSigmas" in dto["vwap"]
    assert "cvdDivergence" in dto["orderFlow"]
    assert "nearestLevel" in dto["location"]
    assert dto["absorption"] is None or "side" in dto["absorption"]


def _aggression_long_ohlc():
    """Deterministic AGGRESSION-LONG session (same trace as the system e2e):

    quiet bars @100 -> t55 volume-spike absorption (500 vol, 450 buys, flat) ->
    near-POC accumulation -> t59 breakout to 104 (> vwap.upper_1) AGGRESSION/LONG.
    """
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


def test_bridge_decision_stored_when_mode_shadow(monkeypatch):
    monkeypatch.setattr(SettingsAdapter, "QUANT_EXECUTION_MODE", "shadow")
    br = QuantBridge()
    session = SessionState(symbol="SYM")
    last_dto = {}
    for bar in _aggression_long_ohlc():
        last_dto = br.on_bar_close_with_decision("SYM", bar, session, _LONG_FACTS)
    assert last_dto["tripleAPhase"] == "AGGRESSION"  # auction DTO still returned
    assert session.last_quant_decision is not None
    assert session.last_quant_decision["approved"] is True
    assert session.last_quant_decision["reason"] == "Triple-A"
    assert session.last_quant_decision["signal"]["type"] == "LONG"
    assert session.last_quant_decision["signal"]["entry"] == pytest.approx(104.0)


def test_bridge_decision_skipped_when_mode_off(monkeypatch):
    monkeypatch.setattr(SettingsAdapter, "QUANT_EXECUTION_MODE", "off")
    br = QuantBridge()
    session = SessionState(symbol="SYM")
    last_dto = {}
    for bar in _aggression_long_ohlc():
        last_dto = br.on_bar_close_with_decision("SYM", bar, session, _LONG_FACTS)
    assert last_dto["tripleAPhase"] == "AGGRESSION"
    assert session.last_quant_decision is None  # off -> legacy path untouched


def test_quant_decision_to_dto_serializes_signal_and_skip():
    from quant.decision.context import DecisionContext
    from quant.decision.decision_service import DecisionService
    from quant.auction_state import AuctionState
    from quant.volume_profile import VolumeProfile
    from quant.vwap import VWAPState
    from quant.order_flow import OrderFlowState
    from quant.location import LocationState

    state = AuctionState(
        time="t", close=100.0,
        volume_profile=VolumeProfile(levels=(), poc=100.0, vah=100.5, val=99.5,
                                     step=0.1, total_volume=100),
        vwap=VWAPState(value=100.0, upper_1=101.0, lower_1=99.0,
                       upper_2=102.0, lower_2=98.0, std=1, deviation_sigmas=0),
        order_flow=OrderFlowState(delta=0, cvd=0.0, cvd_slope=0.0,
                                  cvd_divergence="NONE", aggressive_prints=()),
        absorption=None,
        location=LocationState(ib_high=105, ib_low=95, ib_complete=True,
                               zone="INSIDE_VA", nearest_level=100.0, distance_to_level=0),
        triple_a_phase="AGGRESSION", triple_a_signal="LONG",
    )
    decision = DecisionService().evaluate(
        DecisionContext(state=state, bar=None, agent_direction="LONG",
                        agent_probability=0.7)
    )
    dto = quant_decision_to_dto(decision)
    assert dto["approved"] is True
    assert dto["phase"] == "AGGRESSION"
    assert dto["signal"]["type"] == "LONG"
    assert set(dto["signal"]) == {"type", "entry", "sl", "tp", "rr", "confidence"}
    rejected = quant_decision_to_dto(
        type("Q", (), {"approved": False, "reason": "NO_EDGE", "phase": "WAITING",
                        "signal": None})()
    )
    assert rejected["approved"] is False and rejected["signal"] is None
