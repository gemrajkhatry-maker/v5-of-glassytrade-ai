"""Tests for Session Phase Gate — CHANGE 1."""

from datetime import datetime

import pytest

from app.domain.services.session_phase_gate import (
    SessionPhaseGate,
    TradingPhase,
    AllowedAction,
    PhaseState,
)


class TestSessionPhaseGate:
    def _ts(self, hour: int, minute: int, day: str = "TUESDAY"):
        """Create a test datetime at given IST time on given day."""
        # April 2026: 1=Wed, 2=Thu, 3=Fri, 4=Sat, 5=Sun, 6=Mon, 7=Tue
        day_map = {"MON": 6, "TUE": 7, "WED": 1, "THU": 2, "FRI": 3}
        day_num = day_map.get(day[:3], 7)
        return datetime(2026, 4, day_num, hour, minute)

    def test_before_market_closed(self):
        gate = SessionPhaseGate()
        state = gate.evaluate(self._ts(9, 0, "TUE"))
        assert state.phase == TradingPhase.CLOSED
        assert state.is_blocked

    def test_opening_noise_blocked(self):
        gate = SessionPhaseGate()
        state = gate.evaluate(self._ts(9, 20, "TUE"))
        assert state.phase == TradingPhase.OPENING_NOISE
        assert state.is_blocked
        assert state.allowed_action == AllowedAction.NO_TRADE

    def test_monday_extended_opening(self):
        gate = SessionPhaseGate()
        state = gate.evaluate(self._ts(9, 35, "MON"))
        assert state.phase == TradingPhase.OPENING_NOISE
        assert state.is_blocked  # still in extended opening

    def test_aaa_window(self):
        gate = SessionPhaseGate()
        state = gate.evaluate(self._ts(10, 0, "TUE"))
        assert state.phase == TradingPhase.AAA_WINDOW
        assert not state.is_blocked
        assert state.allowed_action == AllowedAction.ALL_MODELS

    def test_midday_mr_only(self):
        gate = SessionPhaseGate()
        state = gate.evaluate(self._ts(12, 0, "TUE"))
        assert state.phase == TradingPhase.MIDDAY
        assert state.allowed_action == AllowedAction.MR_ONLY
        assert not state.is_blocked

    def test_power_hour(self):
        gate = SessionPhaseGate()
        state = gate.evaluate(self._ts(14, 30, "TUE"))
        assert state.phase == TradingPhase.POWER_HOUR
        assert state.allowed_action == AllowedAction.ALL_MODELS

    def test_close_protection(self):
        gate = SessionPhaseGate()
        state = gate.evaluate(self._ts(15, 20, "TUE"))
        assert state.phase == TradingPhase.CLOSE_PROTECTION
        assert state.is_blocked
        assert state.allowed_action == AllowedAction.EXIT_ONLY

    def test_after_close(self):
        gate = SessionPhaseGate()
        state = gate.evaluate(self._ts(15, 35, "TUE"))
        assert state.phase == TradingPhase.CLOSED
        assert state.is_blocked

    def test_thursday_size_reduction(self):
        gate = SessionPhaseGate()
        state = gate.evaluate(self._ts(10, 0, "THU"))
        assert state.size_multiplier == 0.5
        assert state.allowed_action == AllowedAction.AAA_ONLY

    def test_event_day_blocked(self):
        gate = SessionPhaseGate(event_dates=["2026-04-07"])
        state = gate.evaluate(self._ts(10, 0, "TUE"))  # April 7 = Tuesday
        assert state.is_event_day
        assert state.is_blocked
        assert state.allowed_action == AllowedAction.NO_TRADE

    def test_can_trade_method(self):
        gate = SessionPhaseGate()
        assert gate.can_trade(self._ts(10, 0, "TUE")) is True
        assert gate.can_trade(self._ts(9, 20, "TUE")) is False
        assert gate.can_trade(self._ts(15, 20, "TUE")) is False

    def test_is_aaa_allowed(self):
        gate = SessionPhaseGate()
        assert gate.is_aaa_allowed(self._ts(10, 0, "TUE")) is True
        assert gate.is_aaa_allowed(self._ts(12, 0, "TUE")) is False  # MR only

    def test_is_mr_allowed(self):
        gate = SessionPhaseGate()
        assert gate.is_mr_allowed(self._ts(10, 0, "TUE")) is True
        assert gate.is_mr_allowed(self._ts(12, 0, "TUE")) is True  # MR_ONLY

    def test_friday_reduce(self):
        gate = SessionPhaseGate(friday_reduce=True)
        state = gate.evaluate(self._ts(14, 30, "FRI"))
        assert state.size_multiplier == 0.5
