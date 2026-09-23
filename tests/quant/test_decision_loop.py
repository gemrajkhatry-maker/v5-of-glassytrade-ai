"""Tests for DecisionLoop — extracted decision pipeline.

Tests the DecisionLoop in isolation using mock dependencies. Covers:
- Entry guards (exposure, debounce, risk halt, cooldown)
- Context building and strategy evaluation
- Option signal translation
- Risk ceiling checks
- Sizing and OMS submission
- Signal blocking / latch behavior
- Certification recording
- Advisor notifications
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock


from quant.decision.context import DecisionContext
from quant.decision.decision_service import QuantDecision
from quant.decision.signal_builder import Signal
from quant.engine.decision_loop import DecisionLoop, _as_counter
from quant.events import (
    DecisionProduced,
    PositionOpened,
    SignalApproved,
    SignalBlocked,
)
from quant.execution.exposure import ExposureState


# ---------------------------------------------------------------------------
# Test helpers and fixtures
# ---------------------------------------------------------------------------

@dataclass
class FakeBar:
    """Minimal bar for testing."""
    time: str = "2026-01-15T10:00:00+05:30"
    open: float = 100.0
    high: float = 105.0
    low: float = 95.0
    close: float = 102.0
    volume: float = 1000.0


@dataclass
class FakeRiskState:
    """Minimal risk state for testing."""
    trades_today: int = 0
    equity: float = 100000.0
    daily_pnl: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    consecutive_losses: int = 0
    risk_per_trade_pct: float = 0.005
    cushion_tier: str = "normal"
    session_r: float = 0.0
    peak_daily_pnl: float = 0.0


class FakeRisk:
    """Mock SessionRisk for testing."""

    def __init__(self, can_trade: bool = True, no_trade_reason: str = ""):
        self._can_trade = can_trade
        self._no_trade_reason = no_trade_reason
        self._state = FakeRiskState()
        self.model_sizing_failures = 0

    def can_trade(self) -> tuple[bool, str]:
        return self._can_trade, self._no_trade_reason

    def state(self) -> FakeRiskState:
        return self._state

    def position_size(
        self, entry: float, sl: float, *, lot_size: float = 1.0,
        is_expiry: bool = False, max_lots: int | None = None,
        forecast: Any = None, side: str = "",
    ) -> float:
        return lot_size * 1  # 1 lot


class FakeOMS:
    """Mock OMS for testing."""

    is_live = False

    def __init__(self, lot_size: float = 1.0, submit_raises: Exception | None = None):
        self.lot_size = lot_size
        self.last_fill = None
        self._submit_raises = submit_raises
        self.submitted: list[tuple[Signal, float]] = []

    def submit(self, signal: Signal, quantity: float) -> Any:
        if self._submit_raises is not None:
            raise self._submit_raises
        self.submitted.append((signal, quantity))
        return MagicMock(id="pos-1", open_price=signal.entry, size=quantity)


class FakePortfolioRisk:
    """Mock PortfolioRiskAuthority for testing."""

    def __init__(self, can_accept: bool = True, register_open: bool = True):
        self._can_accept = can_accept
        self._register_open = register_open
        self.released: list[tuple[float, str]] = []
        self.registered: list[tuple[float, str]] = []

    def can_accept(self, trade_risk: float, *, symbol: str = "") -> tuple[bool, str]:
        if self._can_accept:
            return True, ""
        return False, "portfolio ceiling breached"

    def register_open(self, trade_risk: float, *, symbol: str = "") -> bool:
        self.registered.append((trade_risk, symbol))
        return self._register_open

    def release(self, amount: float, *, symbol: str = "") -> None:
        self.released.append((amount, symbol))


class FakeAMTEngine:
    """Mock AMTEngine for testing."""

    def __init__(self, warm_bars: int = 20, interval_seconds: int = 300):
        self.warm_bars = warm_bars
        self.interval_seconds = interval_seconds
        self.last_amt_dto: dict = {}


class FakePositionManager:
    """Mock PositionManager for testing."""

    def __init__(self):
        self.current_position = None


def make_signal(**overrides) -> Signal:
    """Create a test Signal with sensible defaults."""
    defaults = dict(
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
    defaults.update(overrides)
    return Signal(**defaults)


def make_decision(
    approved: bool = True,
    signal: Signal | None = None,
    reason: str = "Triple-A",
    **overrides,
) -> QuantDecision:
    """Create a test QuantDecision."""
    if signal is None and approved:
        signal = make_signal()
    return QuantDecision(
        approved=approved,
        signal=signal,
        reason=reason,
        phase="",
        gate_results=(),
        block_reasons=overrides.get("block_reasons", ()),
        model_label=overrides.get("model_label", "Triple-A" if approved else ""),
    )


class FakeStrategy:
    """Mock TradingStrategy for testing."""

    def __init__(self, decision: QuantDecision | None = None):
        self._decision = decision or make_decision()
        self.last_ctx: DecisionContext | None = None

    def should_enter(self, ctx: DecisionContext, *, allow_positioned: bool = False) -> QuantDecision:
        self.last_ctx = ctx
        return self._decision


def make_decision_loop(
    *,
    strategy: FakeStrategy | None = None,
    risk: FakeRisk | None = None,
    oms: FakeOMS | None = None,
    portfolio_risk: FakePortfolioRisk | None = None,
    amt_engine: FakeAMTEngine | None = None,
    bar_index: int = 10,
    last_close_bar_index: int = -1,
    cooldown_bars: int = 5,
    execution_enabled: bool = True,
    underlying_gateway: Any = None,
    advisor: Any = None,
    forecast_fn: Any = None,
    exposure_state: ExposureState | None = None,
    emit: Any = None,
    greeks: Any = None,
    symbol: str = "NIFTY24JAN100CE",
) -> DecisionLoop:
    """Build a DecisionLoop with test-friendly defaults."""
    _bar_index = bar_index
    _entry_bar_index = 0
    _latch: dict[tuple[str, str], str] = {}
    _cert_records: list[dict] = []
    _recent_decisions: deque[dict] = deque(maxlen=5)
    _open_trade_risk = 0.0
    _exposure_state = exposure_state

    def _set_open_trade_risk(v: float) -> None:
        nonlocal _open_trade_risk
        _open_trade_risk = v

    return DecisionLoop(
        config={
            "symbol": symbol,
            "market": "NSE",
            "contract_expiry": None,
            "tick_size": 0.05,
            "cooldown_bars": cooldown_bars,
            "max_lots": None,
        },
        deps={
            "risk": risk or FakeRisk(),
            "portfolio_risk": portfolio_risk,
            "oms": oms or FakeOMS(),
            "strategy": strategy or FakeStrategy(),
            "amt_engine": amt_engine or FakeAMTEngine(),
            "get_position_manager": lambda: FakePositionManager(),
            "execution_model": None,
            "contract": None,
            "underlying_gateway": underlying_gateway,
            "execution_enabled": execution_enabled,
            "get_underlying_symbol": lambda: "NIFTY FUT",
            "greeks": greeks,
        },
        state={
            "get_bar_index": lambda: _bar_index,
            "get_entry_bar_index": lambda: _entry_bar_index,
            "set_entry_bar_index": lambda v: None,
            "get_last_close_bar_index": lambda: last_close_bar_index,
            "get_latch": lambda: _latch,
            "set_latch": lambda k, v: _latch.update({k: v}),
            "clear_latch": lambda: _latch.clear(),
            "pop_latch": lambda k: _latch.pop(k, None),
            "get_cert_records": lambda: _cert_records,
            "get_last_depth": lambda: None,
            "get_recent_decisions": lambda: list(_recent_decisions),
            "get_open_trade_risk": lambda: _open_trade_risk,
            "set_open_trade_risk": _set_open_trade_risk,
            "get_exposure_state": lambda: _exposure_state,
            "set_exposure_state": lambda v: None,
            "set_entry_time_epoch": lambda v: None,
            "set_last_rejected_bar_index": lambda: None,
        },
        emit=emit or (lambda event: None),
        forecast_fn=forecast_fn,
        advisor=advisor,
    )


# ---------------------------------------------------------------------------
# Tests: _as_counter utility
# ---------------------------------------------------------------------------

class TestAsCounter:
    def test_int_passthrough(self):
        assert _as_counter(5) == 5

    def test_string_int(self):
        assert _as_counter("3") == 3

    def test_none_returns_zero(self):
        assert _as_counter(None) == 0

    def test_mock_returns_nonzero(self):
        """MagicMock can be coerced to int (returns 1) — this is expected."""
        # MagicMock supports __int__ and returns 1 by default.
        # The _as_counter function handles this gracefully.
        result = _as_counter(MagicMock())
        assert isinstance(result, int)

    def test_float_truncates(self):
        assert _as_counter(3.7) == 3


# ---------------------------------------------------------------------------
# Tests: Entry guards
# ---------------------------------------------------------------------------

class TestEntryGuards:
    def test_blocks_on_exposure_reconciliation(self):
        """When broker exposure requires reconciliation, entry is blocked."""
        exposure = ExposureState.none().partial_entry(
            symbol="TEST", order_id="ord-1",
            requested_qty=10, filled_qty=5, fill_price=100.0,
        )
        loop = make_decision_loop(exposure_state=exposure)
        bar = FakeBar()
        result = loop.evaluate({}, bar)
        assert result is None  # blocked by guard

    def test_blocks_on_risk_halt(self):
        """When risk says cannot trade, a HALTED decision is emitted."""
        risk = FakeRisk(can_trade=False, no_trade_reason="max trades reached")
        emitted: list[Any] = []
        loop = make_decision_loop(risk=risk)
        loop._emit = emitted.append
        bar = FakeBar()

        result = loop.evaluate({}, bar)

        assert result is None
        # Should have emitted a HALTED DecisionProduced
        halted = [e for e in emitted if isinstance(e, DecisionProduced)]
        assert len(halted) == 1
        assert halted[0].decision.reason == "HALTED"
        assert "max trades reached" in halted[0].decision.block_reasons[0]

    def test_blocks_on_cooldown(self):
        """When within cooldown period, a COOLDOWN decision is emitted."""
        emitted: list[Any] = []
        # bar_index=6, last_close=3, cooldown_bars=5 -> 2 bars remaining
        loop = make_decision_loop(
            bar_index=6, last_close_bar_index=3, cooldown_bars=5,
        )
        loop._emit = emitted.append
        bar = FakeBar()

        result = loop.evaluate({}, bar)

        assert result is None
        cooldown = [e for e in emitted if isinstance(e, DecisionProduced)]
        assert len(cooldown) == 1
        assert cooldown[0].decision.reason == "COOLDOWN"

    def test_debounce_blocks_rapid_rejection(self):
        """Within 2 bars of a rejection, debounce blocks re-evaluation."""
        loop = make_decision_loop(bar_index=10)
        # Simulate a recent rejection at bar 9
        loop._last_rejected_bar_index = 9
        bar = FakeBar()

        result = loop.evaluate({}, bar)

        assert result is None  # debounced

    def test_debounce_defers_with_logged_reason(self, caplog):
        """Debounce block logs DecisionDeferred reason=DEBOUNCE and counts it."""
        loop = make_decision_loop(bar_index=10)
        loop._last_rejected_bar_index = 9
        bar = FakeBar()

        with caplog.at_level(logging.INFO, logger="quant.engine.decision_loop"):
            result = loop.evaluate({}, bar)

        assert result is None
        deferred = [
            r for r in caplog.records
            if "DecisionDeferred" in r.message and "reason=DEBOUNCE" in r.message
        ]
        assert deferred, "expected DecisionDeferred reason=DEBOUNCE log"
        assert loop._deferred_counts.get("DEBOUNCE") == 1

    def test_startup_block_counts_as_deferral(self, caplog):
        """Startup block already logs ERROR; it also counts as a deferral."""
        loop = make_decision_loop()
        loop._get_startup_block = lambda: True
        bar = FakeBar()

        with caplog.at_level(logging.INFO, logger="quant.engine.decision_loop"):
            result = loop.evaluate({}, bar)

        assert result is None
        deferred = [
            r for r in caplog.records
            if "DecisionDeferred" in r.message and "reason=STARTUP_BLOCK" in r.message
        ]
        assert deferred, "expected DecisionDeferred reason=STARTUP_BLOCK log"
        assert loop._deferred_counts.get("STARTUP_BLOCK") == 1

    def test_no_cooldown_when_no_prior_trade(self):
        """When last_close_bar_index is -1, cooldown is skipped."""
        strategy = FakeStrategy(decision=make_decision())
        loop = make_decision_loop(
            strategy=strategy, bar_index=10, last_close_bar_index=-1,
        )
        bar = FakeBar()

        result = loop.evaluate({}, bar)

        assert result is not None
        assert result.approved is True


# ---------------------------------------------------------------------------
# Tests: Strategy evaluation
# ---------------------------------------------------------------------------

class TestStrategyEvaluation:
    def test_approved_signal_emits_decision_produced(self):
        """An approved strategy decision emits DecisionProduced."""
        emitted: list[Any] = []
        strategy = FakeStrategy(decision=make_decision(approved=True))
        loop = make_decision_loop(strategy=strategy)
        loop._emit = emitted.append
        bar = FakeBar()

        result = loop.evaluate({}, bar)

        assert result is not None
        assert result.approved is True
        decisions = [e for e in emitted if isinstance(e, DecisionProduced)]
        assert len(decisions) == 1

    def test_rejected_signal_clears_latch(self):
        """A rejected decision clears the latch (stale episodes)."""
        strategy = FakeStrategy(decision=make_decision(approved=False, signal=None, reason="NO_EDGE"))
        loop = make_decision_loop(strategy=strategy)
        # Pre-populate latch
        loop._set_latch(("NIFTY24JAN100CE", "LONG"), "some block reason")
        bar = FakeBar()

        result = loop.evaluate({}, bar)

        assert result is not None
        assert result.approved is False
        # Latch should be cleared
        assert len(loop._get_latch()) == 0

    def test_strategy_receives_context(self):
        """The strategy's should_enter receives a DecisionContext."""
        strategy = FakeStrategy(decision=make_decision())
        loop = make_decision_loop(strategy=strategy)
        bar = FakeBar()

        loop.evaluate({"poc": 100.0}, bar)

        assert strategy.last_ctx is not None
        assert strategy.last_ctx.bar is bar


# ---------------------------------------------------------------------------
# Tests: Signal submission
# ---------------------------------------------------------------------------

class TestSignalSubmission:
    def test_approved_signal_submits_to_oms(self):
        """An approved signal is sized and submitted to the OMS."""
        oms = FakeOMS()
        strategy = FakeStrategy(decision=make_decision())
        emitted: list[Any] = []
        loop = make_decision_loop(strategy=strategy, oms=oms)
        loop._emit = emitted.append
        bar = FakeBar()

        loop.evaluate({}, bar)

        assert len(oms.submitted) == 1
        signal, qty = oms.submitted[0]
        assert signal.type == "LONG"
        assert qty > 0

    def test_approved_signal_emits_signal_approved(self):
        """A successful OMS submit emits SignalApproved."""
        oms = FakeOMS()
        strategy = FakeStrategy(decision=make_decision())
        emitted: list[Any] = []
        loop = make_decision_loop(strategy=strategy, oms=oms, emit=emitted.append)
        bar = FakeBar()

        loop.evaluate({}, bar)

        approved = [e for e in emitted if isinstance(e, SignalApproved)]
        assert len(approved) == 1

    def test_approved_signal_emits_position_opened(self):
        """A successful OMS submit emits PositionOpened."""
        oms = FakeOMS()
        strategy = FakeStrategy(decision=make_decision())
        emitted: list[Any] = []
        loop = make_decision_loop(strategy=strategy, oms=oms, emit=emitted.append)
        bar = FakeBar()

        loop.evaluate({}, bar)

        opened = [e for e in emitted if isinstance(e, PositionOpened)]
        assert len(opened) == 1

    def test_oms_failure_emits_signal_blocked(self):
        """When OMS submit raises, SignalBlocked is emitted and risk is unwound."""
        portfolio_risk = FakePortfolioRisk()
        oms = FakeOMS(submit_raises=RuntimeError("broker down"))
        strategy = FakeStrategy(decision=make_decision())
        emitted: list[Any] = []
        loop = make_decision_loop(
            strategy=strategy, oms=oms, portfolio_risk=portfolio_risk,
        )
        loop._emit = emitted.append
        bar = FakeBar()

        loop.evaluate({}, bar)

        blocked = [e for e in emitted if isinstance(e, SignalBlocked)]
        assert len(blocked) == 1
        assert "OMS submit raised" in blocked[0].reason

    def test_oms_failure_unwinds_portfolio_risk(self):
        """When OMS submit raises, the portfolio risk reservation is released."""
        portfolio_risk = FakePortfolioRisk()
        oms = FakeOMS(submit_raises=RuntimeError("broker down"))
        strategy = FakeStrategy(decision=make_decision())
        loop = make_decision_loop(
            strategy=strategy, oms=oms, portfolio_risk=portfolio_risk,
        )
        bar = FakeBar()

        loop.evaluate({}, bar)

        assert len(portfolio_risk.released) == 1

    def test_zero_quantity_blocks(self):
        """When sizing returns 0 lots, the signal is blocked."""
        risk = FakeRisk()
        risk.position_size = lambda *a, **kw: 0  # 0 lots
        strategy = FakeStrategy(decision=make_decision())
        emitted: list[Any] = []
        loop = make_decision_loop(strategy=strategy, risk=risk)
        loop._emit = emitted.append
        bar = FakeBar()

        loop.evaluate({}, bar)

        blocked = [e for e in emitted if isinstance(e, SignalBlocked)]
        assert len(blocked) == 1
        assert "0 lots" in blocked[0].reason

    def test_execution_disabled_skips_submit(self):
        """When execution_enabled=False, approved signals are not submitted."""
        oms = FakeOMS()
        strategy = FakeStrategy(decision=make_decision())
        loop = make_decision_loop(
            strategy=strategy, oms=oms, execution_enabled=False,
        )
        bar = FakeBar()

        loop.evaluate({}, bar)

        assert len(oms.submitted) == 0


# ---------------------------------------------------------------------------
# Tests: Risk ceilings
# ---------------------------------------------------------------------------

class TestRiskCeilings:
    def test_portfolio_risk_can_accept_false_blocks(self):
        """When portfolio risk says no, the signal is blocked."""
        portfolio_risk = FakePortfolioRisk(can_accept=False)
        strategy = FakeStrategy(decision=make_decision())
        emitted: list[Any] = []
        loop = make_decision_loop(
            strategy=strategy, portfolio_risk=portfolio_risk,
        )
        loop._emit = emitted.append
        bar = FakeBar()

        loop.evaluate({}, bar)

        blocked = [e for e in emitted if isinstance(e, SignalBlocked)]
        assert len(blocked) == 1
        assert "portfolio ceiling" in blocked[0].reason

    def test_portfolio_risk_register_failure_blocks(self):
        """When register_open fails, the signal is blocked."""
        portfolio_risk = FakePortfolioRisk(can_accept=True, register_open=False)
        strategy = FakeStrategy(decision=make_decision())
        emitted: list[Any] = []
        loop = make_decision_loop(
            strategy=strategy, portfolio_risk=portfolio_risk,
        )
        loop._emit = emitted.append
        bar = FakeBar()

        loop.evaluate({}, bar)

        blocked = [e for e in emitted if isinstance(e, SignalBlocked)]
        assert len(blocked) == 1
        assert "portfolio cap breached" in blocked[0].reason

    def test_no_portfolio_risk_passes_through(self):
        """When portfolio_risk is None, the ceiling check passes."""
        oms = FakeOMS()
        strategy = FakeStrategy(decision=make_decision())
        loop = make_decision_loop(strategy=strategy, oms=oms, portfolio_risk=None)
        bar = FakeBar()

        loop.evaluate({}, bar)

        assert len(oms.submitted) == 1


# ---------------------------------------------------------------------------
# Tests: Latch / signal blocking
# ---------------------------------------------------------------------------

class TestLatchBehavior:
    def test_first_block_emits_signal_blocked(self):
        """First occurrence of a block emits SignalBlocked."""
        risk = FakeRisk()
        risk.position_size = lambda *a, **kw: 0
        strategy = FakeStrategy(decision=make_decision())
        emitted: list[Any] = []
        loop = make_decision_loop(strategy=strategy, risk=risk)
        loop._emit = emitted.append
        bar = FakeBar()

        loop.evaluate({}, bar)

        blocked = [e for e in emitted if isinstance(e, SignalBlocked)]
        assert len(blocked) == 1

    def test_repeat_block_is_latched(self):
        """Same signal blocked for same reason is latched (debug only)."""
        risk = FakeRisk()
        risk.position_size = lambda *a, **kw: 0
        strategy = FakeStrategy(decision=make_decision())
        emitted: list[Any] = []
        loop = make_decision_loop(strategy=strategy, risk=risk)
        loop._emit = emitted.append
        bar = FakeBar()

        # First evaluation
        loop.evaluate({}, bar)
        first_count = len([e for e in emitted if isinstance(e, SignalBlocked)])

        # Reset debounce so second evaluation runs
        loop._last_rejected_bar_index = -999

        # Second evaluation (same block reason)
        loop.evaluate({}, bar)
        second_count = len([e for e in emitted if isinstance(e, SignalBlocked)])

        # Only one SignalBlocked emitted (second was latched)
        assert first_count == 1
        assert second_count == 1  # no new SignalBlocked


# ---------------------------------------------------------------------------
# Tests: Certification recording
# ---------------------------------------------------------------------------

class TestCertificationRecording:
    def test_decision_recorded_in_cert_buffer(self):
        """An approved decision is recorded in the certification buffer."""
        cert_records: list[dict] = []
        strategy = FakeStrategy(decision=make_decision())
        loop = make_decision_loop(strategy=strategy)
        loop._get_cert_records = lambda: cert_records
        bar = FakeBar()

        loop.evaluate({}, bar)

        decision_recs = [r for r in cert_records if r.get("stage") == "decision"]
        assert len(decision_recs) == 1
        assert decision_recs[0]["approved"] is True

    def test_context_trace_recorded(self):
        """A context-stage certification record is appended."""
        cert_records: list[dict] = []
        strategy = FakeStrategy(decision=make_decision())
        loop = make_decision_loop(strategy=strategy)
        loop._get_cert_records = lambda: cert_records
        bar = FakeBar()

        loop.evaluate({}, bar)

        context_recs = [r for r in cert_records if r.get("stage") == "context"]
        assert len(context_recs) == 1
        assert "market_data" in context_recs[0]


# ---------------------------------------------------------------------------
# Tests: Advisor notifications
# ---------------------------------------------------------------------------

class TestAdvisorNotifications:
    def test_advisor_notified_on_decision(self):
        """The advisor receives context on each decision evaluation."""
        advisor = MagicMock()
        strategy = FakeStrategy(decision=make_decision())
        loop = make_decision_loop(strategy=strategy, advisor=advisor)
        bar = FakeBar()

        loop.evaluate({}, bar)

        advisor.on_context.assert_called()

    def test_advisor_failure_does_not_break_loop(self):
        """Advisor exceptions are caught and do not break the decision loop."""
        advisor = MagicMock()
        advisor.on_context.side_effect = RuntimeError("advisor crashed")
        strategy = FakeStrategy(decision=make_decision())
        oms = FakeOMS()
        loop = make_decision_loop(strategy=strategy, advisor=advisor, oms=oms)
        bar = FakeBar()

        # Should not raise
        result = loop.evaluate({}, bar)

        assert result is not None
        assert result.approved is True
        assert len(oms.submitted) == 1


# ---------------------------------------------------------------------------
# Tests: Forecast
# ---------------------------------------------------------------------------

class TestForecast:
    def test_forecast_fn_called_for_sizing(self):
        """The forecast function is called during sizing."""
        forecast = MagicMock(return_value=None)
        strategy = FakeStrategy(decision=make_decision())
        loop = make_decision_loop(strategy=strategy, forecast_fn=forecast)
        bar = FakeBar()

        loop.evaluate({}, bar)

        forecast.assert_called()

    def test_no_forecast_fn_returns_none(self):
        """When no forecast_fn is provided, sizing uses None."""
        strategy = FakeStrategy(decision=make_decision())
        loop = make_decision_loop(strategy=strategy, forecast_fn=None)
        bar = FakeBar()

        # Should not raise
        result = loop.evaluate({}, bar)
        assert result is not None


# ---------------------------------------------------------------------------
# Tests: AnalysisSnapshot threading (Task 4)
# ---------------------------------------------------------------------------

class TestSnapshotThreading:
    def test_build_context_passes_engine_last_snapshot(self, monkeypatch):
        """DecisionContextBuilder.build receives amt_engine.last_snapshot."""
        snap = object()
        amt_engine = FakeAMTEngine()
        amt_engine.last_snapshot = snap
        loop = make_decision_loop(amt_engine=amt_engine)
        captured: dict[str, Any] = {}

        def capture_build(self, **kwargs):
            captured.update(kwargs)
            return MagicMock(spec=DecisionContext)

        monkeypatch.setattr(
            "quant.engine.decision_loop.DecisionContextBuilder.build",
            capture_build,
        )
        bar = FakeBar()
        loop._build_context(bar, {"poc": 100.0}, 0.0)

        assert captured.get("snapshot") is snap
        assert captured.get("amt_dto") == {"poc": 100.0}


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_amt_dto_uses_last(self):
        """When amt_dto is empty, the AMT engine's last DTO is used."""
        amt_engine = FakeAMTEngine()
        amt_engine.last_amt_dto = {"poc": 100.0, "valueAreaHigh": 105.0}
        strategy = FakeStrategy(decision=make_decision())
        loop = make_decision_loop(strategy=strategy, amt_engine=amt_engine)
        bar = FakeBar()

        result = loop.evaluate(None, bar)

        assert result is not None

    def test_evaluate_returns_decision(self):
        """evaluate() returns the QuantDecision when guards pass."""
        strategy = FakeStrategy(decision=make_decision(approved=True))
        loop = make_decision_loop(strategy=strategy)
        bar = FakeBar()

        result = loop.evaluate({}, bar)

        assert isinstance(result, QuantDecision)
        assert result.approved is True

    def test_evaluate_returns_none_on_guard_block(self):
        """evaluate() returns None when an entry guard blocks."""
        risk = FakeRisk(can_trade=False, no_trade_reason="halted")
        loop = make_decision_loop(risk=risk)
        bar = FakeBar()

        result = loop.evaluate({}, bar)

        assert result is None


# ---------------------------------------------------------------------------
# Tests: Option translation seam (P0-3 production wire)
# ---------------------------------------------------------------------------

class TestOptionTranslationSeam:
    def test_gateway_plus_greeks_submits_premium_scaled_signal(self):
        """underlying_gateway + DictGreeks → OMS gets option premium levels."""
        from quant.contracts.ports.greeks import DictGreeks

        contract = "NIFTY 24600 CALL"
        underlying_signal = make_signal(
            entry=25000.0, sl=24980.0, tp=25040.0, rr=2.0, symbol="NIFTY FUT",
        )
        strategy = FakeStrategy(decision=make_decision(signal=underlying_signal))
        oms = FakeOMS()
        greeks = DictGreeks({contract: 0.55})
        loop = make_decision_loop(
            strategy=strategy,
            oms=oms,
            underlying_gateway=object(),
            greeks=greeks,
            symbol=contract,
        )
        # Underlying bar for strategy; execution_bar is the option premium tape.
        und_bar = FakeBar(close=25000.0, open=24990.0, high=25010.0, low=24980.0)
        opt_bar = FakeBar(close=100.0, open=99.0, high=101.0, low=98.0)

        result = loop.evaluate({}, und_bar, execution_bar=opt_bar)

        assert result is not None
        assert result.approved is True
        assert len(oms.submitted) == 1
        submitted, _qty = oms.submitted[0]
        assert submitted.symbol == contract
        assert submitted.entry == 100.0
        assert submitted.sl == 89.0
        assert submitted.tp == 122.0

    def test_gateway_without_greeks_refuses_data_degraded(self):
        """Missing Greeks on a translated engine → DATA_DEGRADED, not OMS."""
        contract = "NIFTY 24600 CALL"
        underlying_signal = make_signal(
            entry=25000.0, sl=24980.0, tp=25040.0, symbol="NIFTY FUT",
        )
        strategy = FakeStrategy(decision=make_decision(signal=underlying_signal))
        oms = FakeOMS()
        loop = make_decision_loop(
            strategy=strategy,
            oms=oms,
            underlying_gateway=object(),
            greeks=None,
            symbol=contract,
        )
        und_bar = FakeBar(close=25000.0)
        opt_bar = FakeBar(close=100.0)

        result = loop.evaluate({}, und_bar, execution_bar=opt_bar)

        assert result is not None
        assert result.approved is False
        assert result.reason == "DATA_DEGRADED"
        assert oms.submitted == []
