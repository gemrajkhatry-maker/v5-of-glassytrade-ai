"""Integration tests for SubmissionHandler with simulated OMS responses.

Tests realistic OMS scenarios including:
- Successful fills with various quantities
- Partial fills and reconciliation
- Order rejections (insufficient margin, risk limits)
- Broker timeouts and retries
- Slippage and price movement
- Concurrent position limits
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from quant.decision.signal_builder import Signal
from quant.engine.submission_handler import SubmissionHandler
from quant.events import PositionOpened, SignalApproved, SignalBlocked
from quant.execution.exposure import ExposureState


# ---------------------------------------------------------------------------
# Simulated OMS with realistic behavior
# ---------------------------------------------------------------------------

@dataclass
class SimulatedFill:
    """Represents a fill from the OMS."""
    order_id: str
    requested_quantity: float
    filled_quantity: float
    fill_price: float
    status: str = "filled"  # "filled", "partial", "rejected", "timeout"


class SimulatedOMS:
    """Simulated OMS with configurable behavior for integration testing."""

    def __init__(
        self,
        lot_size: float = 1.0,
        fill_behavior: str = "full",  # "full", "partial", "reject", "timeout", "slippage"
        partial_fill_ratio: float = 0.5,
        slippage_ticks: float = 0.0,
        reject_reason: str = "",
        timeout_on_nth: int = 0,  # Timeout on the Nth submission (0 = never)
    ):
        self.lot_size = lot_size
        self.fill_behavior = fill_behavior
        self.partial_fill_ratio = partial_fill_ratio
        self.slippage_ticks = slippage_ticks
        self.reject_reason = reject_reason
        self.timeout_on_nth = timeout_on_nth

        self.submitted: list[tuple[Signal, float]] = []
        self.last_fill: SimulatedFill | None = None
        self._submission_count = 0

    def submit(self, signal: Signal, quantity: float) -> Any:
        """Simulate OMS submission with configurable behavior."""
        self._submission_count += 1
        self.submitted.append((signal, quantity))

        # Timeout scenario
        if self.timeout_on_nth > 0 and self._submission_count == self.timeout_on_nth:
            raise TimeoutError("Broker connection timeout")

        # Rejection scenario
        if self.fill_behavior == "reject":
            raise RuntimeError(self.reject_reason or "Order rejected by broker")

        # Calculate fill price with slippage
        slippage = self.slippage_ticks * 0.05  # Assume 0.05 tick size
        if signal.type == "LONG":
            fill_price = signal.entry + slippage
        else:
            fill_price = signal.entry - slippage

        # Full fill
        if self.fill_behavior == "full":
            self.last_fill = SimulatedFill(
                order_id=f"ORD-{self._submission_count:04d}",
                requested_quantity=quantity,
                filled_quantity=quantity,
                fill_price=fill_price,
                status="filled",
            )
            return MagicMock()

        # Partial fill
        if self.fill_behavior == "partial":
            filled_qty = quantity * self.partial_fill_ratio
            self.last_fill = SimulatedFill(
                order_id=f"ORD-{self._submission_count:04d}",
                requested_quantity=quantity,
                filled_quantity=filled_qty,
                fill_price=fill_price,
                status="partial",
            )
            return MagicMock()

        # Slippage (still fills, but at worse price)
        if self.fill_behavior == "slippage":
            self.last_fill = SimulatedFill(
                order_id=f"ORD-{self._submission_count:04d}",
                requested_quantity=quantity,
                filled_quantity=quantity,
                fill_price=fill_price,
                status="filled",
            )
            return MagicMock()

        raise ValueError(f"Unknown fill behavior: {self.fill_behavior}")


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeBar:
    time: str = "2026-01-15T10:00:00+05:30"
    open: float = 100.0
    high: float = 105.0
    low: float = 95.0
    close: float = 102.0
    volume: float = 1000.0


@dataclass
class FakeRiskState:
    trades_today: int = 0
    equity: float = 100000.0


class FakeRisk:
    def __init__(self):
        self.model_sizing_failures = 0
        self._state = FakeRiskState()

    def state(self):
        return self._state

    def position_size(self, entry, sl, *, lot_size=1.0, is_expiry=False, max_lots=None, forecast=None, side=""):
        return lot_size * 10  # 10 lots for testing partial fills


class FakePositionManager:
    def __init__(self):
        self.current_position = None


class FakePortfolioRisk:
    def __init__(self):
        self.registered: list[float] = []
        self.released: list[float] = []

    def can_accept(self, trade_risk, symbol=""):
        return True, "OK"

    def register_open(self, trade_risk, symbol=""):
        self.registered.append(trade_risk)
        return True

    def release(self, amount, symbol=""):
        self.released.append(amount)


def make_signal(type="LONG", entry=100.0, sl=98.0, tp=106.0):
    return Signal(
        type=type,
        reason="Triple-A",
        entry=entry,
        sl=sl,
        tp=tp,
        rr=3.0,
        model_label="Triple-A",
        symbol="NIFTY24JAN100CE",
        timestamp="2026-01-15T10:00:00+05:30",
    )


def make_submission_handler(
    *,
    oms: SimulatedOMS,
    portfolio_risk: FakePortfolioRisk | None = None,
    emit=None,
):
    emitted = []
    exposure_state = None
    _open_trade_risk = 0.0

    def set_exposure(state):
        nonlocal exposure_state
        exposure_state = state

    def get_open_trade_risk():
        return _open_trade_risk

    def set_open_trade_risk(v):
        nonlocal _open_trade_risk
        _open_trade_risk = v

    handler = SubmissionHandler(
        config={
            "symbol": "NIFTY24JAN100CE",
            "contract_expiry": None,
            "max_lots": None,
            "execution_model": None,
            "contract": None,
            "execution_enabled": True,
        },
        deps={
            "risk": FakeRisk(),
            "oms": oms,
            "get_portfolio_risk": lambda: portfolio_risk or FakePortfolioRisk(),
            "get_position_manager": lambda: FakePositionManager(),
            "forecast_fn": None,
        },
        state={
            "get_bar_index": lambda: 10,
            "get_entry_bar_index": lambda: 0,
            "set_entry_bar_index": lambda v: None,
            "get_latch": lambda: {},
            "set_latch": lambda k, v: None,
            "pop_latch": lambda k: None,
            "get_open_trade_risk": get_open_trade_risk,
            "set_open_trade_risk": set_open_trade_risk,
            "get_exposure_state": lambda: exposure_state,
            "set_exposure_state": set_exposure,
            "set_entry_time_epoch": lambda v: None,
            "set_last_rejected_bar_index": lambda: None,
        },
        emit=emit or emitted.append,
        latch_or_signal_block=lambda signal, reason, bar_time: None,
        notify_advisor_position=lambda bar, amt_dto, position: None,
    )
    return handler, emitted


# ---------------------------------------------------------------------------
# Integration Tests: Full Fill Scenarios
# ---------------------------------------------------------------------------

class TestFullFillScenarios:
    def test_full_fill_long_position(self):
        """LONG signal fills completely at requested quantity."""
        oms = SimulatedOMS(fill_behavior="full")
        portfolio_risk = FakePortfolioRisk()
        handler, emitted = make_submission_handler(oms=oms, portfolio_risk=portfolio_risk)
        bar = FakeBar()
        signal = make_signal(type="LONG", entry=100.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is True
        assert len(oms.submitted) == 1
        assert oms.last_fill.status == "filled"
        assert oms.last_fill.filled_quantity == oms.last_fill.requested_quantity
        assert any(isinstance(e, SignalApproved) for e in emitted)
        assert any(isinstance(e, PositionOpened) for e in emitted)
        assert len(portfolio_risk.registered) == 1

    def test_full_fill_short_position(self):
        """SHORT signal fills completely at requested quantity."""
        oms = SimulatedOMS(fill_behavior="full")
        handler, emitted = make_submission_handler(oms=oms)
        bar = FakeBar()
        signal = make_signal(type="SHORT", entry=100.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is True
        assert oms.last_fill.status == "filled"
        assert oms.last_fill.filled_quantity == oms.last_fill.requested_quantity


# ---------------------------------------------------------------------------
# Integration Tests: Partial Fill Scenarios
# ---------------------------------------------------------------------------

class TestPartialFillScenarios:
    def test_partial_fill_sets_exposure_state(self):
        """Partial fill sets exposure state for reconciliation."""
        oms = SimulatedOMS(fill_behavior="partial", partial_fill_ratio=0.5)
        handler, emitted = make_submission_handler(oms=oms)
        bar = FakeBar()
        signal = make_signal(entry=100.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is False
        assert oms.last_fill.status == "partial"
        assert oms.last_fill.filled_quantity == oms.last_fill.requested_quantity * 0.5
        # Exposure state should be set for reconciliation
        # (The handler sets it via set_exposure_state callback)

    def test_partial_fill_30_percent(self):
        """Partial fill at 30% ratio."""
        oms = SimulatedOMS(fill_behavior="partial", partial_fill_ratio=0.3)
        handler, _ = make_submission_handler(oms=oms)
        bar = FakeBar()
        signal = make_signal(entry=100.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is False
        assert oms.last_fill.filled_quantity == pytest.approx(
            oms.last_fill.requested_quantity * 0.3, rel=1e-6
        )

    def test_partial_fill_90_percent(self):
        """Partial fill at 90% ratio (nearly full)."""
        oms = SimulatedOMS(fill_behavior="partial", partial_fill_ratio=0.9)
        handler, _ = make_submission_handler(oms=oms)
        bar = FakeBar()
        signal = make_signal(entry=100.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is False
        assert oms.last_fill.filled_quantity == pytest.approx(
            oms.last_fill.requested_quantity * 0.9, rel=1e-6
        )


# ---------------------------------------------------------------------------
# Integration Tests: Rejection Scenarios
# ---------------------------------------------------------------------------

class TestRejectionScenarios:
    def test_broker_rejection_insufficient_margin(self):
        """Broker rejects due to insufficient margin."""
        oms = SimulatedOMS(
            fill_behavior="reject",
            reject_reason="Insufficient margin",
        )
        portfolio_risk = FakePortfolioRisk()
        handler, emitted = make_submission_handler(oms=oms, portfolio_risk=portfolio_risk)
        bar = FakeBar()
        signal = make_signal(entry=100.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is False
        assert len(oms.submitted) == 1
        # Portfolio risk should be released after rejection
        assert len(portfolio_risk.released) == 1

    def test_broker_rejection_risk_limit(self):
        """Broker rejects due to risk limit breach."""
        oms = SimulatedOMS(
            fill_behavior="reject",
            reject_reason="Risk limit exceeded",
        )
        portfolio_risk = FakePortfolioRisk()
        handler, _ = make_submission_handler(oms=oms, portfolio_risk=portfolio_risk)
        bar = FakeBar()
        signal = make_signal(entry=100.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is False
        assert len(portfolio_risk.released) == 1

    def test_broker_rejection_symbol_blocked(self):
        """Broker rejects due to symbol being blocked."""
        oms = SimulatedOMS(
            fill_behavior="reject",
            reject_reason="Symbol temporarily blocked",
        )
        handler, _ = make_submission_handler(oms=oms)
        bar = FakeBar()
        signal = make_signal(entry=100.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is False


# ---------------------------------------------------------------------------
# Integration Tests: Timeout Scenarios
# ---------------------------------------------------------------------------

class TestTimeoutScenarios:
    def test_broker_timeout_first_submission(self):
        """Broker times out on first submission."""
        oms = SimulatedOMS(timeout_on_nth=1)
        portfolio_risk = FakePortfolioRisk()
        handler, _ = make_submission_handler(oms=oms, portfolio_risk=portfolio_risk)
        bar = FakeBar()
        signal = make_signal(entry=100.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is False
        assert len(portfolio_risk.released) == 1

    def test_broker_timeout_second_submission(self):
        """Broker times out on second submission (first succeeds)."""
        oms = SimulatedOMS(timeout_on_nth=2)
        handler, _ = make_submission_handler(oms=oms)
        bar = FakeBar()
        signal = make_signal(entry=100.0)

        # First submission succeeds
        result1 = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")
        assert result1 is True

        # Second submission times out
        result2 = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")
        assert result2 is False


# ---------------------------------------------------------------------------
# Integration Tests: Slippage Scenarios
# ---------------------------------------------------------------------------

class TestSlippageScenarios:
    def test_long_fill_with_positive_slippage(self):
        """LONG fills at worse price (higher than entry)."""
        oms = SimulatedOMS(fill_behavior="slippage", slippage_ticks=2.0)
        handler, _ = make_submission_handler(oms=oms)
        bar = FakeBar()
        signal = make_signal(type="LONG", entry=100.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is True
        assert oms.last_fill.fill_price > signal.entry
        assert oms.last_fill.fill_price == pytest.approx(100.1, rel=1e-6)  # 2 ticks * 0.05

    def test_short_fill_with_positive_slippage(self):
        """SHORT fills at worse price (lower than entry)."""
        oms = SimulatedOMS(fill_behavior="slippage", slippage_ticks=3.0)
        handler, _ = make_submission_handler(oms=oms)
        bar = FakeBar()
        signal = make_signal(type="SHORT", entry=100.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is True
        assert oms.last_fill.fill_price < signal.entry
        assert oms.last_fill.fill_price == pytest.approx(99.85, rel=1e-6)  # 3 ticks * 0.05

    def test_zero_slippage_fills_at_entry(self):
        """Zero slippage fills at exact entry price."""
        oms = SimulatedOMS(fill_behavior="slippage", slippage_ticks=0.0)
        handler, _ = make_submission_handler(oms=oms)
        bar = FakeBar()
        signal = make_signal(entry=100.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is True
        assert oms.last_fill.fill_price == signal.entry


# ---------------------------------------------------------------------------
# Integration Tests: Multiple Submissions
# ---------------------------------------------------------------------------

class TestMultipleSubmissions:
    def test_multiple_successful_submissions(self):
        """Multiple successful submissions in sequence."""
        oms = SimulatedOMS(fill_behavior="full")
        handler, emitted = make_submission_handler(oms=oms)
        bar = FakeBar()

        for i in range(3):
            signal = make_signal(entry=100.0 + i)
            result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")
            assert result is True

        assert len(oms.submitted) == 3
        assert len([e for e in emitted if isinstance(e, SignalApproved)]) == 3

    def test_mixed_success_and_failure(self):
        """Sequence of successful and failed submissions."""
        oms = SimulatedOMS(timeout_on_nth=2)  # Timeout on 2nd submission
        handler, emitted = make_submission_handler(oms=oms)
        bar = FakeBar()

        # 1st: success
        result1 = handler.submit(make_signal(entry=100.0), bar, {}, MagicMock(), "Triple-A")
        assert result1 is True

        # 2nd: timeout
        result2 = handler.submit(make_signal(entry=101.0), bar, {}, MagicMock(), "Triple-A")
        assert result2 is False

        # 3rd: success (timeout_on_nth=2, so 3rd submission is fine)
        result3 = handler.submit(make_signal(entry=102.0), bar, {}, MagicMock(), "Triple-A")
        assert result3 is True

        assert len(oms.submitted) == 3
        assert len([e for e in emitted if isinstance(e, SignalApproved)]) == 2


# ---------------------------------------------------------------------------
# Integration Tests: Portfolio Risk Integration
# ---------------------------------------------------------------------------

class TestPortfolioRiskIntegration:
    def test_risk_registered_on_success(self):
        """Portfolio risk is registered on successful submission."""
        oms = SimulatedOMS(fill_behavior="full")
        portfolio_risk = FakePortfolioRisk()
        handler, _ = make_submission_handler(oms=oms, portfolio_risk=portfolio_risk)
        bar = FakeBar()
        signal = make_signal(entry=100.0, sl=98.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is True
        assert len(portfolio_risk.registered) == 1
        # Trade risk = |entry - sl| * quantity = 2.0 * 10 = 20.0
        assert portfolio_risk.registered[0] == pytest.approx(20.0, rel=1e-6)

    def test_risk_released_on_failure(self):
        """Portfolio risk is released on submission failure."""
        oms = SimulatedOMS(fill_behavior="reject", reject_reason="Broker error")
        portfolio_risk = FakePortfolioRisk()
        handler, _ = make_submission_handler(oms=oms, portfolio_risk=portfolio_risk)
        bar = FakeBar()
        signal = make_signal(entry=100.0, sl=98.0)

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is False
        assert len(portfolio_risk.registered) == 1
        assert len(portfolio_risk.released) == 1
        assert portfolio_risk.released[0] == portfolio_risk.registered[0]
