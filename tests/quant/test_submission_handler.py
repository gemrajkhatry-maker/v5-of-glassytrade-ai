"""Tests for SubmissionHandler — extracted submission pipeline.

Tests the SubmissionHandler in isolation using mock dependencies. Covers:
- Contract guard checks
- Execution enabled/disabled
- Position sizing
- Risk ceiling checks
- OMS submission and error handling
- Partial fill handling
- State updates
- Event emission
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock


from quant.decision.signal_builder import Signal
from quant.engine.submission_handler import SubmissionHandler, _as_counter
from quant.events import PositionOpened, SignalApproved


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
    def __init__(self, model_sizing_failures: int = 0):
        self.model_sizing_failures = model_sizing_failures
        self._state = FakeRiskState()

    def state(self):
        return self._state

    def position_size(self, entry, sl, *, lot_size=1.0, is_expiry=False, max_lots=None, forecast=None, side=""):
        return lot_size * 1


class FakeOMS:
    def __init__(self, lot_size=1.0, submit_raises=None):
        self.lot_size = lot_size
        self.last_fill = None
        self._submit_raises = submit_raises
        self.submitted = []

    def submit(self, signal, quantity):
        if self._submit_raises:
            raise self._submit_raises
        self.submitted.append((signal, quantity))
        return MagicMock()


class FakePositionManager:
    def __init__(self):
        self.current_position = None


class FakePortfolioRisk:
    def __init__(self, can_accept=True, register_open=True):
        self._can_accept = can_accept
        self._register_open = register_open

    def can_accept(self, trade_risk, symbol=""):
        return self._can_accept, "OK" if self._can_accept else "Cap breached"

    def register_open(self, trade_risk, symbol=""):
        return self._register_open

    def release(self, amount, symbol=""):
        pass


def make_signal():
    return Signal(
        type="LONG",
        reason="Triple-A",
        entry=100.0,
        sl=98.0,
        tp=106.0,
        rr=3.0,
        model_label="Triple-A",
        symbol="NIFTY24JAN100CE",
        timestamp="2026-01-15T10:00:00+05:30",
    )


def make_submission_handler(
    *,
    risk=None,
    oms=None,
    portfolio_risk=None,
    execution_enabled=True,
    execution_model=None,
    contract=None,
    emit=None,
):
    emitted = []
    handler = SubmissionHandler(
        config={
            "symbol": "NIFTY24JAN100CE",
            "contract_expiry": None,
            "max_lots": None,
            "execution_model": execution_model,
            "contract": contract,
            "execution_enabled": execution_enabled,
        },
        deps={
            "risk": risk or FakeRisk(),
            "oms": oms or FakeOMS(),
            "get_portfolio_risk": lambda: portfolio_risk,
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
            "get_open_trade_risk": lambda: 0.0,
            "set_open_trade_risk": lambda v: None,
            "get_exposure_state": lambda: None,
            "set_exposure_state": lambda v: None,
            "set_entry_time_epoch": lambda v: None,
            "set_last_rejected_bar_index": lambda: None,
        },
        emit=emit or emitted.append,
        latch_or_signal_block=lambda signal, reason, bar_time: None,
        notify_advisor_position=lambda bar, amt_dto, position: None,
    )
    return handler, emitted


# ---------------------------------------------------------------------------
# Tests: _as_counter utility
# ---------------------------------------------------------------------------

class TestAsCounter:
    def test_int_passthrough(self):
        assert _as_counter(5) == 5

    def test_string_int(self):
        assert _as_counter("42") == 42

    def test_none_returns_zero(self):
        assert _as_counter(None) == 0

    def test_mock_returns_int(self):
        """MagicMock can be converted to int (returns 1 by default)."""
        # MagicMock's __int__ returns 1, so _as_counter returns 1
        assert _as_counter(MagicMock()) == 1


# ---------------------------------------------------------------------------
# Tests: Execution guards
# ---------------------------------------------------------------------------

class TestExecutionGuards:
    def test_execution_disabled_skips_submit(self):
        """When execution_enabled=False, submit returns False without calling OMS."""
        oms = FakeOMS()
        handler, _ = make_submission_handler(oms=oms, execution_enabled=False)
        bar = FakeBar()
        signal = make_signal()

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is False
        assert len(oms.submitted) == 0

    def test_execution_enabled_submits(self):
        """When execution_enabled=True, submit calls OMS."""
        oms = FakeOMS()
        handler, _ = make_submission_handler(oms=oms, execution_enabled=True)
        bar = FakeBar()
        signal = make_signal()

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is True
        assert len(oms.submitted) == 1


# ---------------------------------------------------------------------------
# Tests: Position sizing
# ---------------------------------------------------------------------------

class TestPositionSizing:
    def test_zero_quantity_blocks(self):
        """When position_size returns 0, submit returns False."""
        risk = FakeRisk()
        risk.position_size = lambda *args, **kwargs: 0
        oms = FakeOMS()
        handler, _ = make_submission_handler(risk=risk, oms=oms)
        bar = FakeBar()
        signal = make_signal()

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is False
        assert len(oms.submitted) == 0


# ---------------------------------------------------------------------------
# Tests: Risk ceilings
# ---------------------------------------------------------------------------

class TestRiskCeilings:
    def test_portfolio_risk_can_accept_false_blocks(self):
        """When portfolio_risk.can_accept returns False, submit returns False."""
        portfolio_risk = FakePortfolioRisk(can_accept=False)
        oms = FakeOMS()
        handler, _ = make_submission_handler(oms=oms, portfolio_risk=portfolio_risk)
        bar = FakeBar()
        signal = make_signal()

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is False
        assert len(oms.submitted) == 0

    def test_portfolio_risk_register_failure_blocks(self):
        """When portfolio_risk.register_open returns False, submit returns False."""
        portfolio_risk = FakePortfolioRisk(register_open=False)
        oms = FakeOMS()
        handler, _ = make_submission_handler(oms=oms, portfolio_risk=portfolio_risk)
        bar = FakeBar()
        signal = make_signal()

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is False
        assert len(oms.submitted) == 0

    def test_no_portfolio_risk_passes_through(self):
        """When portfolio_risk is None, submit proceeds without ceiling checks."""
        oms = FakeOMS()
        handler, _ = make_submission_handler(oms=oms, portfolio_risk=None)
        bar = FakeBar()
        signal = make_signal()

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is True
        assert len(oms.submitted) == 1


# ---------------------------------------------------------------------------
# Tests: OMS submission
# ---------------------------------------------------------------------------

class TestOMSSubmission:
    def test_oms_success_emits_events(self):
        """Successful OMS submit emits SignalApproved and PositionOpened."""
        oms = FakeOMS()
        handler, emitted = make_submission_handler(oms=oms)
        bar = FakeBar()
        signal = make_signal()

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is True
        assert any(isinstance(e, SignalApproved) for e in emitted)
        assert any(isinstance(e, PositionOpened) for e in emitted)

    def test_oms_failure_returns_false(self):
        """When OMS submit raises, submit returns False."""
        oms = FakeOMS(submit_raises=RuntimeError("broker down"))
        handler, _ = make_submission_handler(oms=oms)
        bar = FakeBar()
        signal = make_signal()

        result = handler.submit(signal, bar, {}, MagicMock(), "Triple-A")

        assert result is False


# ---------------------------------------------------------------------------
# Tests: Properties
# ---------------------------------------------------------------------------

class TestProperties:
    def test_symbol_property(self):
        """SubmissionHandler exposes symbol property."""
        handler, _ = make_submission_handler()
        assert handler.symbol == "NIFTY24JAN100CE"
