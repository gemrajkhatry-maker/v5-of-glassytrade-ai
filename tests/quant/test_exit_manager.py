"""Tests for ExitManager — extracted exit pipeline.

Tests the ExitManager in isolation using mock dependencies. Covers:
- Bar-driven exit evaluation (manage_exit)
- Tick-level fast exit (manage_tick_exit)
- Thesis flip evaluation (check_thesis_flip)
- Full close execution (execute_full_close)
- Partial close with reserve release (_release_partial_reserves)
- Full close bookkeeping (_book_full_close)
- Double-close guard
- Pyramid handling in full close
- Lingering pyramid close (close_lingering_pyramids)
- Advisor notifications
- Error handling (OMS failures, C3 containment)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch


from quant.engine.exit_manager import ExitManager, close_lingering_pyramids
from quant.events import DecisionProduced


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
class FakeSignal:
    """Minimal signal for testing."""
    type: str = "LONG"
    entry: float = 100.0
    sl: float = 95.0
    tp: float = 110.0
    rr: float = 2.0
    symbol: str = "TEST"
    model_label: str = "AMT"
    reason: str = "BREAKOUT"


@dataclass
class FakeOrder:
    """Minimal order for testing."""
    signal: FakeSignal = field(default_factory=FakeSignal)


@dataclass
class FakePosition:
    """Minimal position for testing."""
    _id: str = "pos-001"
    id: str = "pos-001"
    size: float = 10.0
    open_price: float = 100.0
    order: FakeOrder = field(default_factory=FakeOrder)
    pyramid_level: int = 0


@dataclass
class FakeFill:
    """Minimal fill for testing."""
    pnl: float = 50.0
    position: FakePosition = field(default_factory=FakePosition)
    filled_quantity: float = 10.0
    requested_quantity: float = 10.0
    order_id: str = "order-001"
    fill_price: float = 105.0


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


class FakeRisk:
    """Mock SessionRisk for testing."""

    def __init__(self):
        self._state = FakeRiskState()
        self.model_sizing_failures = 0

    def state(self) -> FakeRiskState:
        return self._state


class FakeEngineState:
    """Mock EngineState for testing."""

    def __init__(self, position=None):
        self.position = position
        self.last_bar = None

    def with_position(self, pos):
        return FakeEngineState(position=pos)


class FakePortfolioRisk:
    """Mock PortfolioRiskAuthority for testing."""

    def __init__(self):
        self.open_risk = 0.0
        self.close_calls = []

    def record_close(self, risk: float, pnl: float, **kwargs) -> None:
        self.close_calls.append({"risk": risk, "pnl": pnl, **kwargs})
        self.open_risk -= risk


class FakePositionManager:
    """Mock PositionManager for testing."""

    def __init__(self):
        self.current_position = None
        self.pyramid_positions = []
        self.pyramid_count = 0
        self.last_fill = None
        self.last_partial_fill = None
        self.last_pyramid_pnl = 0.0
        self._closed_ids = set()
        self._pyramid_open_risk = {}
        self._portfolio_risk = None
        self.symbol = "TEST"
        # Track calls for assertions
        self.manage_exit_calls = []
        self.manage_tick_exit_calls = []
        self.execute_full_close_calls = []

    def manage_exit(self, **kwargs):
        self.manage_exit_calls.append(kwargs)
        # Default: return None (full close)
        return None

    def manage_tick_exit(self, position, tick_price, tick_time):
        self.manage_tick_exit_calls.append({
            "position": position, "tick_price": tick_price, "tick_time": tick_time,
        })
        return None

    def _execute_full_close(self, position, exit_dec, time_str, **kwargs):
        self.execute_full_close_calls.append({
            "position": position, "exit_dec": exit_dec, "time_str": time_str,
            **kwargs,
        })
        fill = FakeFill()
        self.last_fill = fill
        return fill


class FakeAMTEngine:
    """Mock AMT engine for testing."""

    def __init__(self):
        self.last_amt_dto = {}
        self.warm_bars = 5


class FakeAggregator:
    """Mock aggregator for testing."""

    def __init__(self):
        self.interval_seconds = 300
        self.current_bar = FakeBar()


class FakeStrategy:
    """Mock strategy for testing."""

    def __init__(self, approved=False, signal=None, reason=""):
        self._approved = approved
        self._signal = signal
        self._reason = reason

    def should_enter(self, ctx, allow_positioned=False):
        from quant.decision.decision_service import QuantDecision
        return QuantDecision(
            approved=self._approved,
            signal=self._signal if self._approved else None,
            reason=self._reason or ("APPROVED" if self._approved else "NO_EDGE"),
            phase="TEST",
            gate_results=(),
            block_reasons=() if self._approved else ("NO_EDGE",),
            model_label="TEST",
        )


class FakeExitDecision:
    """Mock exit decision from strategy."""

    def __init__(self, approved=True, signal=None, reason=""):
        self.approved = approved
        self.signal = signal or (FakeSignal() if approved else None)
        self.reason = reason


def make_quant_decision(approved=False, signal=None, reason="NO_EDGE"):
    """Create a QuantDecision for testing."""
    from quant.decision.decision_service import QuantDecision
    return QuantDecision(
        approved=approved,
        signal=signal,
        reason=reason,
        phase="TEST",
        gate_results=(),
        block_reasons=() if approved else (reason,),
        model_label="TEST",
    )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _make_exit_manager(
    *,
    symbol: str = "TEST",
    market: str = "NSE",
    portfolio_risk=None,
    position_manager=None,
    strategy=None,
    state_position=None,
    emit_fn=None,
    forecast_fn=None,
    advisor=None,
    underlying_gateway=None,
    underlying_amt_dto=None,
    last_underlying_bar=None,
    risk=None,
    close_lock=None,
) -> ExitManager:
    """Build an ExitManager wired to fake/mock dependencies."""
    pm = position_manager or FakePositionManager()
    risk = risk or FakeRisk()
    emitted = []

    def _emit(event):
        emitted.append(event)
        if emit_fn:
            emit_fn(event)

    config = {
        "symbol": symbol,
        "market": market,
        "contract_expiry": None,
        "tick_size": 0.05,
        "cooldown_bars": 3,
    }
    fake_state = FakeEngineState(position=state_position)
    state_obj = {"value": fake_state}

    deps = {
        "get_position_manager": lambda: pm,
        "portfolio_risk": portfolio_risk,
        "strategy": strategy or FakeStrategy(),
        "amt_engine": FakeAMTEngine(),
        "aggregator": FakeAggregator(),
        "get_underlying_symbol": lambda: "UNDERLYING",
        "close_lock": close_lock or threading.Lock(),
        "underlying_gateway": underlying_gateway,
        "risk": risk,
    }
    state = {
        "get_bar_index": lambda: 10,
        "get_entry_bar_index": lambda: 5,
        "get_entry_time_epoch": lambda: 1000.0,
        "get_last_close_bar_index": lambda: -1,
        "set_last_close_bar_index": lambda v: None,
        "get_open_trade_risk": lambda: 100.0,
        "set_open_trade_risk": lambda v: None,
        "get_state": lambda: state_obj["value"],
        "set_state": lambda v: state_obj.__setitem__("value", v),
        "get_last_depth": lambda: None,
        "get_recent_decisions": lambda: [],
        "get_underlying_amt_dto": lambda: underlying_amt_dto,
        "get_last_underlying_bar": lambda: last_underlying_bar,
        "get_option_amt_dto": lambda: None,
    }
    mgr = ExitManager(
        config=config,
        deps=deps,
        state=state,
        emit=_emit,
        forecast_fn=forecast_fn,
        advisor=advisor,
    )
    # Expose test internals
    mgr._emitted = emitted
    mgr._pm = pm
    mgr._state_obj = state_obj
    return mgr


# ---------------------------------------------------------------------------
# Tests: manage_exit (bar-driven exit evaluation)
# ---------------------------------------------------------------------------

class TestManageExit:
    """Tests for ExitManager.manage_exit()."""

    def test_full_close_when_position_closed(self):
        """When PositionManager returns None, book_full_close is called."""
        pm = FakePositionManager()
        pm.current_position = FakePosition()
        mgr = _make_exit_manager(position_manager=pm, state_position=FakePosition())

        result = mgr.manage_exit({}, FakeBar())

        assert result is None
        assert len(pm.manage_exit_calls) == 1

    def test_partial_close_returns_remaining(self):
        """When PositionManager returns a reduced position, it survives."""
        pm = FakePositionManager()
        original_pos = FakePosition()
        remaining_pos = FakePosition(_id="pos-001", size=5.0)
        pm.current_position = original_pos
        pm.manage_exit = lambda **kwargs: remaining_pos  # type: ignore

        mgr = _make_exit_manager(position_manager=pm, state_position=original_pos)

        result = mgr.manage_exit({}, FakeBar())

        assert result is remaining_pos
        assert pm.current_position is remaining_pos

    def test_no_position_returns_none(self):
        """When no position is open, manage_exit returns None."""
        pm = FakePositionManager()
        pm.current_position = None
        mgr = _make_exit_manager(position_manager=pm)

        result = mgr.manage_exit({}, FakeBar())

        assert result is None
        # PositionManager.manage_exit is called but returns None for no position
        assert pm.current_position is None

    def test_oms_failure_keeps_position_open(self):
        """C3: OMS failure during exit must not kill the engine thread."""
        pm = FakePositionManager()
        original_pos = FakePosition()
        pm.current_position = original_pos

        def failing_manage_exit(**kwargs):
            raise RuntimeError("OMS connection lost")

        pm.manage_exit = failing_manage_exit
        mgr = _make_exit_manager(position_manager=pm, state_position=original_pos)

        # Should not raise — C3 containment
        result = mgr.manage_exit({}, FakeBar())

        # Position is kept open for retry
        assert result is original_pos

    def test_triggers_thesis_flip_when_position_survives(self):
        """When position survives, thesis flip evaluation runs."""
        pm = FakePositionManager()
        surviving_pos = FakePosition(size=5.0)
        pm.current_position = FakePosition()
        pm.manage_exit = lambda **kwargs: surviving_pos  # type: ignore

        # Strategy returns opposing signal
        opposing_signal = FakeSignal(type="SHORT", reason="BREAKOUT")
        strategy = FakeStrategy(approved=True, signal=opposing_signal)
        mgr = _make_exit_manager(
            position_manager=pm,
            state_position=FakePosition(),
            strategy=strategy,
        )

        with patch.object(mgr, "check_thesis_flip") as mock_flip:
            mgr.manage_exit({}, FakeBar())
            mock_flip.assert_called_once()

    def test_no_thesis_flip_when_position_closed(self):
        """When position is fully closed, thesis flip is NOT evaluated."""
        pm = FakePositionManager()
        pm.current_position = FakePosition()
        pm.manage_exit = lambda **kwargs: None  # type: ignore (full close)
        mgr = _make_exit_manager(position_manager=pm, state_position=FakePosition())

        with patch.object(mgr, "check_thesis_flip") as mock_flip:
            mgr.manage_exit({}, FakeBar())
            mock_flip.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: manage_tick_exit (tick-level fast exit)
# ---------------------------------------------------------------------------

class TestManageTickExit:
    """Tests for ExitManager.manage_tick_exit()."""

    def test_no_position_returns_immediately(self):
        """When no position is open, tick exit does nothing."""
        pm = FakePositionManager()
        pm.current_position = None
        mgr = _make_exit_manager(position_manager=pm)

        mgr.manage_tick_exit(100.0, "2026-01-15T10:00:00+05:30")

        assert len(pm.manage_tick_exit_calls) == 0

    def test_full_close_on_sl_breach(self):
        """When tick breaches SL, position is fully closed."""
        pm = FakePositionManager()
        pm.current_position = FakePosition()
        # Use the default manage_tick_exit which returns None (full close)
        # and tracks calls via manage_tick_exit_calls
        mgr = _make_exit_manager(
            position_manager=pm, state_position=FakePosition(),
        )

        mgr.manage_tick_exit(90.0, "2026-01-15T10:00:00+05:30")

        assert pm.current_position is None
        assert len(pm.manage_tick_exit_calls) == 1
        assert pm.manage_tick_exit_calls[0]["tick_price"] == 90.0

    def test_partial_close_updates_position(self):
        """When tick triggers a partial, the reduced position survives."""
        pm = FakePositionManager()
        original_pos = FakePosition()
        remaining_pos = FakePosition(size=5.0)
        pm.current_position = original_pos
        pm.manage_tick_exit = lambda pos, price, time: remaining_pos  # type: ignore
        mgr = _make_exit_manager(
            position_manager=pm, state_position=original_pos,
        )

        mgr.manage_tick_exit(105.0, "2026-01-15T10:00:00+05:30")

        assert pm.current_position is remaining_pos

    def test_clears_stale_partial_state(self):
        """Per-call state is cleared to prevent duplicate reserve releases."""
        pm = FakePositionManager()
        pm.current_position = FakePosition()
        pm.last_partial_fill = FakeFill()  # stale from previous call
        pm.last_pyramid_pnl = 42.0  # stale from previous call
        pm.manage_tick_exit = lambda pos, price, time: pos  # type: ignore (survives)
        mgr = _make_exit_manager(position_manager=pm, state_position=FakePosition())

        mgr.manage_tick_exit(100.0, "2026-01-15T10:00:00+05:30")

        # Stale state should be cleared at the start of the call
        assert pm.last_pyramid_pnl == 0.0

    def test_oms_failure_keeps_position_open(self):
        """C3: OMS failure during tick exit must not kill the engine thread."""
        pm = FakePositionManager()
        pm.current_position = FakePosition()

        def failing_tick_exit(pos, price, time):
            raise RuntimeError("OMS connection lost")

        pm.manage_tick_exit = failing_tick_exit
        mgr = _make_exit_manager(position_manager=pm, state_position=FakePosition())

        # Should not raise — C3 containment
        mgr.manage_tick_exit(90.0, "2026-01-15T10:00:00+05:30")


# ---------------------------------------------------------------------------
# Tests: check_thesis_flip (opposing signal exit)
# ---------------------------------------------------------------------------

class TestCheckThesisFlip:
    """Tests for ExitManager.check_thesis_flip()."""

    def test_no_position_returns_immediately(self):
        """When no position is open, thesis flip does nothing."""
        pm = FakePositionManager()
        pm.current_position = None
        mgr = _make_exit_manager(position_manager=pm)

        mgr.check_thesis_flip({}, FakeBar())

        assert len(pm.execute_full_close_calls) == 0

    def test_same_direction_no_action(self):
        """When the new signal is the same direction as the held position, no flip."""
        pm = FakePositionManager()
        pos = FakePosition(size=10.0)  # LONG
        pm.current_position = pos
        # Strategy returns same direction (LONG)
        signal = FakeSignal(type="LONG", reason="BREAKOUT")
        strategy = FakeStrategy(approved=True, signal=signal)
        mgr = _make_exit_manager(position_manager=pm, strategy=strategy)

        mgr.check_thesis_flip({}, FakeBar())

        assert len(pm.execute_full_close_calls) == 0

    def test_opposing_signal_triggers_full_close(self):
        """When the new signal opposes the held position, full close is executed."""
        pm = FakePositionManager()
        pos = FakePosition(size=10.0)  # LONG
        pm.current_position = pos
        # Strategy returns opposing signal (SHORT)
        opposing_signal = FakeSignal(type="SHORT", reason="BREAKOUT")
        strategy = FakeStrategy(approved=True, signal=opposing_signal)
        mgr = _make_exit_manager(position_manager=pm, strategy=strategy)

        mgr.check_thesis_flip({}, FakeBar())

        assert len(pm.execute_full_close_calls) == 1
        assert pm.execute_full_close_calls[0]["exit_dec"].reason == "OPPOSING_SIGNAL"

    def test_model_momentum_skipped(self):
        """MODEL_MOMENTUM approvals do not trigger a thesis flip."""
        pm = FakePositionManager()
        pos = FakePosition(size=10.0)  # LONG
        pm.current_position = pos
        opposing_signal = FakeSignal(type="SHORT", reason="MODEL_MOMENTUM")
        strategy = FakeStrategy(approved=True, signal=opposing_signal)
        mgr = _make_exit_manager(position_manager=pm, strategy=strategy)

        mgr.check_thesis_flip({}, FakeBar())

        assert len(pm.execute_full_close_calls) == 0

    def test_unapproved_signal_no_action(self):
        """When the strategy does not approve, no flip occurs."""
        pm = FakePositionManager()
        pos = FakePosition(size=10.0)
        pm.current_position = pos
        strategy = FakeStrategy(approved=False)
        mgr = _make_exit_manager(position_manager=pm, strategy=strategy)

        mgr.check_thesis_flip({}, FakeBar())

        assert len(pm.execute_full_close_calls) == 0

    def test_emits_decision_produced(self):
        """A DecisionProduced event is emitted for the thesis flip evaluation."""
        pm = FakePositionManager()
        pm.current_position = FakePosition()
        strategy = FakeStrategy(approved=False)
        mgr = _make_exit_manager(position_manager=pm, strategy=strategy)

        mgr.check_thesis_flip({}, FakeBar())

        decision_events = [e for e in mgr._emitted if isinstance(e, DecisionProduced)]
        assert len(decision_events) == 1

    def test_underlying_gateway_uses_underlying_context(self):
        """With underlying gateway, thesis flip uses underlying DTO and bar."""
        pm = FakePositionManager()
        pos = FakePosition(size=10.0)
        pm.current_position = pos
        underlying_bar = FakeBar(time="2026-01-15T10:00:00+05:30")
        underlying_amt = {"poc": 100.0}
        strategy = FakeStrategy(approved=True, signal=FakeSignal(type="SHORT"))
        mgr = _make_exit_manager(
            position_manager=pm,
            strategy=strategy,
            underlying_gateway=MagicMock(),
            underlying_amt_dto=underlying_amt,
            last_underlying_bar=underlying_bar,
        )

        mgr.check_thesis_flip({}, FakeBar())

        # Should have used underlying context (not the option bar/dto passed in)
        assert len(pm.execute_full_close_calls) == 1

    def test_underlying_context_unavailable_skips(self):
        """When underlying context is unavailable, thesis flip is skipped."""
        pm = FakePositionManager()
        pm.current_position = FakePosition()
        mgr = _make_exit_manager(
            position_manager=pm,
            underlying_gateway=MagicMock(),
            underlying_amt_dto=None,
            last_underlying_bar=None,
        )

        mgr.check_thesis_flip({}, FakeBar())

        assert len(pm.execute_full_close_calls) == 0

    def test_put_symbol_thesis_mapping(self):
        """For put symbols, thesis direction is mapped from contract type."""
        pm = FakePositionManager()
        pos = FakePosition(size=10.0)  # LONG put = SHORT thesis
        pm.current_position = pos
        # A LONG signal opposes a SHORT thesis on a put
        opposing_signal = FakeSignal(type="LONG", reason="TRIPLE_A")
        strategy = FakeStrategy(approved=True, signal=opposing_signal)
        mgr = _make_exit_manager(
            symbol="NIFTY 20000 PUT",
            position_manager=pm,
            strategy=strategy,
        )

        mgr.check_thesis_flip({}, FakeBar())

        assert len(pm.execute_full_close_calls) == 1


# ---------------------------------------------------------------------------
# Tests: execute_full_close (EOD force close)
# ---------------------------------------------------------------------------

class TestExecuteFullClose:
    """Tests for ExitManager.execute_full_close()."""

    def test_no_position_returns_false(self):
        """When nothing is open, execute_full_close returns False."""
        pm = FakePositionManager()
        pm.current_position = None
        pm.pyramid_positions = []
        mgr = _make_exit_manager(position_manager=pm)

        result = mgr.execute_full_close("SESSION_CLOSE")

        assert result is False

    def test_closes_base_position(self):
        """When a base position is open, it is closed."""
        pm = FakePositionManager()
        pm.current_position = FakePosition()
        mgr = _make_exit_manager(position_manager=pm)

        result = mgr.execute_full_close("SESSION_CLOSE")

        assert result is True
        assert len(pm.execute_full_close_calls) == 1
        assert pm.execute_full_close_calls[0]["exit_dec"].reason == "SESSION_CLOSE"

    def test_closes_lingering_pyramids(self):
        """When base is gone but pyramids linger, they are closed."""
        pm = FakePositionManager()
        pm.current_position = None
        pm.pyramid_positions = [FakePosition(_id="pyr-1", pyramid_level=1)]
        mgr = _make_exit_manager(position_manager=pm)

        result = mgr.execute_full_close("SESSION_CLOSE")

        assert result is True


# ---------------------------------------------------------------------------
# Tests: _release_partial_reserves
# ---------------------------------------------------------------------------

class TestReleasePartialReserves:
    """Tests for ExitManager._release_partial_reserves()."""

    def test_no_portfolio_risk_returns_immediately(self):
        """Without portfolio risk, reserve release is a no-op."""
        pm = FakePositionManager()
        mgr = _make_exit_manager(portfolio_risk=None)

        # Should not raise
        mgr._release_partial_reserves(pm, None)

    def test_no_partial_fill_returns_immediately(self):
        """Without a partial fill, reserve release is a no-op."""
        pm = FakePositionManager()
        pm.last_partial_fill = None
        portfolio_risk = FakePortfolioRisk()
        mgr = _make_exit_manager(portfolio_risk=portfolio_risk)

        mgr._release_partial_reserves(pm, FakePosition())

        assert len(portfolio_risk.close_calls) == 0

    def test_releases_fraction_of_risk(self):
        """Releases the correct fraction of open trade risk."""
        pm = FakePositionManager()
        partial_fill = FakeFill()
        partial_fill.position = FakePosition(size=5.0)  # closed half
        pm.last_partial_fill = partial_fill
        remaining = FakePosition(size=5.0)  # 5 remaining
        portfolio_risk = FakePortfolioRisk()
        mgr = _make_exit_manager(portfolio_risk=portfolio_risk)

        mgr._release_partial_reserves(pm, remaining)

        # fraction = 5 / (5 + 5) = 0.5, release = 100.0 * 0.5 = 50.0
        assert len(portfolio_risk.close_calls) == 1
        assert portfolio_risk.close_calls[0]["risk"] == 50.0


# ---------------------------------------------------------------------------
# Tests: _book_full_close
# ---------------------------------------------------------------------------

class TestBookFullClose:
    """Tests for ExitManager._book_full_close()."""

    def test_records_portfolio_risk_close(self):
        """Full close records the aggregate risk release."""
        pm = FakePositionManager()
        pm.last_fill = FakeFill(pnl=100.0)
        portfolio_risk = FakePortfolioRisk()
        mgr = _make_exit_manager(portfolio_risk=portfolio_risk, position_manager=pm)

        mgr._book_full_close()

        assert len(portfolio_risk.close_calls) == 1
        assert portfolio_risk.close_calls[0]["risk"] == 100.0  # open_trade_risk
        assert portfolio_risk.close_calls[0]["pnl"] == 100.0

    def test_no_portfolio_risk_still_works(self):
        """Full close works without portfolio risk (paper mode)."""
        pm = FakePositionManager()
        pm.last_fill = FakeFill(pnl=50.0)
        mgr = _make_exit_manager(portfolio_risk=None)

        # Should not raise
        mgr._book_full_close()


# ---------------------------------------------------------------------------
# Tests: close_lingering_pyramids (module-level function)
# ---------------------------------------------------------------------------

class TestCloseLingeringPyramids:
    """Tests for the close_lingering_pyramids() module function."""

    def test_closes_all_lingering_pyramids(self):
        """All lingering pyramid add-ons are closed."""
        pm = FakePositionManager()
        pm.pyramid_positions = [
            FakePosition(_id="pyr-1", pyramid_level=1),
            FakePosition(_id="pyr-2", pyramid_level=2),
        ]
        pm._pyramid_open_risk = {"pyr-1": 10.0, "pyr-2": 5.0}
        pm._portfolio_risk = FakePortfolioRisk()

        closed = close_lingering_pyramids(pm, 100.0, "2026-01-15T15:30:00+05:30", "SESSION_CLOSE")

        assert closed == 2
        assert len(pm.execute_full_close_calls) == 2

    def test_handles_id_less_addon(self):
        """Add-ons without an id are skipped and kept in the book."""
        pm = FakePositionManager()
        idless_pos = MagicMock(spec=[])  # no _id or id attributes
        pm.pyramid_positions = [idless_pos]

        closed = close_lingering_pyramids(pm, 100.0, "2026-01-15T15:30:00+05:30", "SESSION_CLOSE")

        assert closed == 0
        assert len(pm.pyramid_positions) == 1  # kept for retry

    def test_handles_close_failure(self):
        """Failed add-on closes are logged and kept for retry."""
        pm = FakePositionManager()
        pm.pyramid_positions = [FakePosition(_id="pyr-1")]

        def failing_close(position, exit_dec, time_str, **kwargs):
            raise RuntimeError("OMS failure")

        pm._execute_full_close = failing_close

        closed = close_lingering_pyramids(pm, 100.0, "2026-01-15T15:30:00+05:30", "SESSION_CLOSE")

        assert closed == 0
        assert len(pm.pyramid_positions) == 1  # kept for retry

    def test_handles_double_close_guard(self):
        """When the close guard refuses, the add-on is kept for retry."""
        pm = FakePositionManager()
        pm.pyramid_positions = [FakePosition(_id="pyr-1")]
        pm._execute_full_close = lambda *args, **kwargs: None  # type: ignore (guard refused)

        closed = close_lingering_pyramids(pm, 100.0, "2026-01-15T15:30:00+05:30", "SESSION_CLOSE")

        assert closed == 0
        assert len(pm.pyramid_positions) == 1  # kept for retry

    def test_empty_pyramid_list(self):
        """No lingering pyramids returns 0."""
        pm = FakePositionManager()
        pm.pyramid_positions = []

        closed = close_lingering_pyramids(pm, 100.0, "2026-01-15T15:30:00+05:30", "SESSION_CLOSE")

        assert closed == 0

    def test_count_as_trade_is_false(self):
        """Pyramid-only flatten uses count_as_trade=False."""
        pm = FakePositionManager()
        pm.pyramid_positions = [FakePosition(_id="pyr-1")]

        close_lingering_pyramids(pm, 100.0, "2026-01-15T15:30:00+05:30", "SESSION_CLOSE")

        assert pm.execute_full_close_calls[0].get("count_as_trade") is False


# ---------------------------------------------------------------------------
# Tests: advisor notifications
# ---------------------------------------------------------------------------

class TestAdvisorNotifications:
    """Tests for advisor notification behavior."""

    def test_advisor_notified_on_exit(self):
        """Advisor is notified after bar-driven exit evaluation."""
        advisor = MagicMock()
        pm = FakePositionManager()
        pm.current_position = FakePosition()
        pm.manage_exit = lambda **kwargs: None  # type: ignore (full close)
        mgr = _make_exit_manager(
            position_manager=pm,
            state_position=FakePosition(),
            advisor=advisor,
        )

        mgr.manage_exit({}, FakeBar())

        # Advisor should be notified (at least once for the exit)
        assert advisor.on_context.called

    def test_advisor_notified_on_full_close(self):
        """Advisor is notified when a position is fully closed."""
        advisor = MagicMock()
        pm = FakePositionManager()
        pm.last_fill = FakeFill()
        mgr = _make_exit_manager(advisor=advisor)

        mgr._book_full_close()

        # Advisor should be notified of the close
        assert advisor.on_context.called

    def test_advisor_failure_does_not_break_exit(self):
        """Advisor notification failure is contained."""
        advisor = MagicMock()
        advisor.on_context.side_effect = RuntimeError("advisor crashed")
        pm = FakePositionManager()
        pm.current_position = FakePosition()
        pm.manage_exit = lambda **kwargs: None  # type: ignore
        mgr = _make_exit_manager(
            position_manager=pm,
            state_position=FakePosition(),
            advisor=advisor,
        )

        # Should not raise
        result = mgr.manage_exit({}, FakeBar())
        assert result is None


# ---------------------------------------------------------------------------
# Tests: context building
# ---------------------------------------------------------------------------

class TestBuildContext:
    """Tests for ExitManager._build_context()."""

    def test_build_context_passes_engine_last_snapshot(self, monkeypatch):
        snap = object()
        pm = FakePositionManager()
        pm.current_position = FakePosition()
        mgr = _make_exit_manager(position_manager=pm)
        mgr._amt_engine.last_snapshot = snap
        captured: dict[str, Any] = {}

        def capture_build(self, **kwargs):
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(
            "quant.engine.exit_manager.DecisionContextBuilder.build",
            capture_build,
        )
        mgr._build_context(FakeBar(), {"poc": 100.0}, 0.0)

        assert captured.get("snapshot") is snap
        assert captured.get("amt_dto") == {"poc": 100.0}

    def test_builds_context_with_position(self):
        """Context is built with the active position."""
        pm = FakePositionManager()
        pos = FakePosition(size=10.0)  # LONG position
        pm.current_position = pos
        mgr = _make_exit_manager(position_manager=pm)

        ctx = mgr._build_context(FakeBar(), {}, 0.0)

        assert ctx is not None
        # DecisionContext exposes position_side, not position object
        assert ctx.position_open is True
        assert ctx.position_side == "LONG"

    def test_builds_context_with_underlying_symbol(self):
        """When underlying gateway is present, context uses underlying symbol."""
        pm = FakePositionManager()
        pm.current_position = FakePosition()
        mgr = _make_exit_manager(
            position_manager=pm,
            underlying_gateway=MagicMock(),
            underlying_amt_dto={"poc": 100.0},
            last_underlying_bar=FakeBar(),
        )

        ctx = mgr._build_context(FakeBar(), {"poc": 100.0}, 0.0)

        assert ctx is not None
        # The context should use the underlying symbol
        assert ctx.symbol == "UNDERLYING"


# ---------------------------------------------------------------------------
# Tests: integration / edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge case and integration tests."""

    def test_concurrent_close_lock(self):
        """Close lock serializes concurrent close attempts."""
        pm = FakePositionManager()
        pm.current_position = FakePosition()
        lock = threading.Lock()
        mgr = _make_exit_manager(position_manager=pm, close_lock=lock, state_position=FakePosition())

        # Simulate concurrent manage_exit and manage_tick_exit
        results = []

        def manage_exit_thread():
            results.append(("manage_exit", mgr.manage_exit({}, FakeBar())))

        def tick_exit_thread():
            results.append(("tick_exit", mgr.manage_tick_exit(90.0, "2026-01-15T10:00:00+05:30")))

        t1 = threading.Thread(target=manage_exit_thread)
        t2 = threading.Thread(target=tick_exit_thread)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both should have completed without error
        assert len(results) == 2

    def test_symbol_property(self):
        """Symbol property returns the configured symbol."""
        mgr = _make_exit_manager(symbol="NIFTY24800CE")
        assert mgr.symbol == "NIFTY24800CE"

    def test_fresh_forecast_returns_none_without_fn(self):
        """Without a forecast function, _fresh_forecast returns None."""
        mgr = _make_exit_manager(forecast_fn=None)
        assert mgr._fresh_forecast() is None

    def test_fresh_forecast_returns_forecast(self):
        """With a forecast function, _fresh_forecast returns its result."""
        forecast = MagicMock()
        mgr = _make_exit_manager(forecast_fn=lambda: forecast)
        assert mgr._fresh_forecast() is forecast

    def test_bars_since_close_no_prior_close(self):
        """Without a prior close, bars_since_close returns cooldown_bars."""
        mgr = _make_exit_manager()
        # last_close_bar_index = -1 (no prior close)
        assert mgr._bars_since_close() == 3  # cooldown_bars

    def test_cooldown_remaining_sec_calculation(self):
        """Cooldown seconds are correctly calculated from bars."""
        mgr = _make_exit_manager()
        # 3 cooldown bars, 300s interval -> 0 remaining when bars_since_close >= 3
        assert mgr._cooldown_remaining_sec(3) == 0.0
        # 0 bars since close -> 3 * 300 = 900 seconds remaining
        assert mgr._cooldown_remaining_sec(0) == 900.0
        # 1 bar since close -> 2 * 300 = 600 seconds remaining
        assert mgr._cooldown_remaining_sec(1) == 600.0
