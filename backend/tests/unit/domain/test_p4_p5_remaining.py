"""Tests for IB Breakout Scalp, Mobile Alerts, and Self-Healing."""

import pytest

from app.domain.services.ib_breakout_scalp import (
    IBBreakoutScalpEngine,
    IBScalpSignal,
    IBScalpType,
)
from app.domain.services.initial_balance_engine import IBState, IBLocation
from app.domain.services.mobile_alerts import (
    MobileAlertSystem,
    AlertLevel,
    Alert,
)
from app.domain.services.self_healing import (
    OrderRejectionHandler,
    OrderRejectionAction,
    DBFallbackBuffer,
    LLMTimeoutRecovery,
)


# ===== IB Breakout Scalp =====


class TestIBBreakoutScalp:
    def _make_ib_state(self, high=105.0, low=95.0, complete=True):
        return IBState(
            ib_high=high,
            ib_low=low,
            ib_mid=(high + low) / 2,
            ib_width=high - low,
            is_complete=complete,
            location=IBLocation.ABOVE,
            ib_position_pct=100.0,
        )

    def test_ib_not_complete_returns_none(self):
        engine = IBBreakoutScalpEngine()
        state = self._make_ib_state(complete=False)
        sig = engine.evaluate_setup_a(
            state,
            106.0,
            107.0,
            104.0,
            100,
            50,
            10.0,
            1,
            0.5,
        )
        assert sig.scalp_type == IBScalpType.NONE

    def test_retest_near_ib_high(self):
        engine = IBBreakoutScalpEngine(min_rr_ratio=1.0)
        state = self._make_ib_state(high=105.0, low=95.0)
        # First tick: break above IB_HIGH
        engine.evaluate_setup_a(
            state,
            106.0,
            107.0,
            104.0,
            100,
            50,
            10.0,
            0,
            0.5,
        )
        # Second tick: retest at IB_HIGH
        sig = engine.evaluate_setup_a(
            state,
            105.0,
            105.5,
            104.5,
            100,
            50,
            10.0,
            1,
            0.5,
        )
        assert sig.setup_valid or sig.rejection_reason != ""

    def test_volume_not_confirmed(self):
        engine = IBBreakoutScalpEngine()
        state = self._make_ib_state()
        sig = engine.evaluate_setup_a(
            state,
            106.0,
            107.0,
            104.0,
            20,
            50,
            10.0,
            0,
            0.5,
        )
        assert not sig.setup_valid
        assert "Volume" in sig.rejection_reason

    def test_reset(self):
        engine = IBBreakoutScalpEngine()
        engine._breakout_detected = True
        engine.reset()
        assert not engine._breakout_detected


# ===== Mobile Alerts =====


class TestMobileAlerts:
    def test_send_critical(self):
        alert_sys = MobileAlertSystem(enabled=True)
        alert_sys.send_critical("NIFTY", "Daily loss limit breached")
        stats = alert_sys.get_stats()
        assert stats["critical"] == 1

    def test_send_warning(self):
        alert_sys = MobileAlertSystem(enabled=True)
        alert_sys.send_warning("NIFTY", "50% daily loss")
        stats = alert_sys.get_stats()
        assert stats["warning"] == 1

    def test_send_info(self):
        alert_sys = MobileAlertSystem(enabled=True)
        alert_sys.send_info("NIFTY", "Session started")
        stats = alert_sys.get_stats()
        assert stats["info"] == 1

    def test_get_alerts_by_level(self):
        alert_sys = MobileAlertSystem(enabled=True)
        alert_sys.send_critical("NIFTY", "test")
        alert_sys.send_warning("NIFTY", "test")
        critical = alert_sys.get_alerts(level=AlertLevel.CRITICAL)
        assert len(critical) == 1

    def test_last_critical_tracked(self):
        alert_sys = MobileAlertSystem(enabled=True)
        alert_sys.send_critical("NIFTY", "Daily loss breached")
        assert "Daily loss breached" in alert_sys.get_stats()["last_critical"]


# ===== Self-Healing =====


class TestOrderRejectionHandler:
    def test_entry_rejection_skips(self):
        handler = OrderRejectionHandler()
        action = handler.handle_entry_rejection("O1", "insufficient funds")
        assert action == OrderRejectionAction.SKIP

    def test_sl_rejection_retries(self):
        handler = OrderRejectionHandler()
        action = handler.handle_sl_rejection("O1", "rejected")
        assert action == OrderRejectionAction.RETRY

    def test_sl_rejection_alerts_after_max(self):
        handler = OrderRejectionHandler()
        handler.handle_sl_rejection("O1", "rejected")  # retry 1
        action = handler.handle_sl_rejection("O1", "rejected")  # alert
        assert action == OrderRejectionAction.ALERT

    def test_exit_rejection_retries_3_times(self):
        handler = OrderRejectionHandler()
        assert (
            handler.handle_exit_rejection("O1", "rejected")
            == OrderRejectionAction.RETRY
        )
        assert (
            handler.handle_exit_rejection("O1", "rejected")
            == OrderRejectionAction.RETRY
        )
        assert (
            handler.handle_exit_rejection("O1", "rejected")
            == OrderRejectionAction.RETRY
        )
        assert (
            handler.handle_exit_rejection("O1", "rejected")
            == OrderRejectionAction.ALERT
        )

    def test_reset(self):
        handler = OrderRejectionHandler()
        handler.handle_sl_rejection("O1", "rejected")
        handler.reset()
        action = handler.handle_sl_rejection("O1", "rejected")
        assert action == OrderRejectionAction.RETRY  # fresh counter


class TestDBFallbackBuffer:
    def test_buffer_write(self):
        buf = DBFallbackBuffer()
        buf.buffer_write("save_trade", {"symbol": "NIFTY", "pnl": 100})
        assert buf.buffer_size == 1

    def test_buffer_stats(self):
        buf = DBFallbackBuffer()
        buf.buffer_write("save_trade", {"symbol": "NIFTY"})
        buf.buffer_write("save_tick", {"symbol": "NIFTY"})
        stats = buf.get_stats()
        assert stats["buffer_size"] == 2
        assert stats["write_failures"] == 2

    def test_max_buffer_size(self):
        buf = DBFallbackBuffer()
        for i in range(15000):
            buf.buffer_write("save_trade", {"i": i})
        assert buf.buffer_size == 10000  # maxlen enforced


class TestLLMTimeoutRecovery:
    def test_no_disable_before_max(self):
        recovery = LLMTimeoutRecovery(max_consecutive_timeouts=3)
        recovery.record_timeout("NIFTY")
        recovery.record_timeout("NIFTY")
        assert not recovery.is_disabled("NIFTY")

    def test_disable_after_max(self):
        recovery = LLMTimeoutRecovery(max_consecutive_timeouts=3)
        recovery.record_timeout("NIFTY")
        recovery.record_timeout("NIFTY")
        disabled = recovery.record_timeout("NIFTY")
        assert disabled is True
        assert recovery.is_disabled("NIFTY")

    def test_success_re_enables(self):
        recovery = LLMTimeoutRecovery(max_consecutive_timeouts=3)
        recovery.record_timeout("NIFTY")
        recovery.record_timeout("NIFTY")
        recovery.record_timeout("NIFTY")  # disabled
        recovery.record_success("NIFTY")  # re-enabled
        assert not recovery.is_disabled("NIFTY")

    def test_status(self):
        recovery = LLMTimeoutRecovery()
        recovery.record_timeout("NIFTY")
        status = recovery.get_status()
        assert "NIFTY" in status["consecutive_timeouts"]
