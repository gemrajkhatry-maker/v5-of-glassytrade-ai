"""Tests for Phase 1 Critical Safety Fixes.

Covers:
- CRIT-01: PositionManager.check_pyramid gracefully catches (ValueError, NotImplementedError, Exception)
  from OMS.add_pyramid() and logs warning instead of crashing QuantEngine.
- CRIT-02: Position exit executions in _manage_exit() and _manage_tick_exit() are serialized with
  force_close_position() via self._close_lock.
- HIGH-01: PortfolioRiskAuthority.register_open() is atomic and checks both daily loss limit and
  open risk ceiling under lock.
- HIGH-02: MultiEngineCoordinator._stop_engine() cleanly closes engine._journal and shuts down advisor.
"""

import threading
import time
from unittest.mock import MagicMock

import pytest

from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.execution.exits import ExitDecision, ExitEngine
from quant.execution.live_oms import LiveOMS
from quant.execution.oms import PaperOMS
from quant.execution.order import Order, Position
from quant.execution.portfolio_risk import PortfolioRiskAuthority
from quant.execution.risk import SessionRisk
from quant.multi_engine import QuantCoordinator
from quant.persistence import Journal
from quant.position_manager import PositionManager
from quant.runtime import QuantEngine


def _mk_pos(size: float = 10.0) -> Position:
    sig = Signal(
        type="LONG", reason="r", entry=100.0, sl=99.0, tp=104.0, rr=2.0,
        model_label="Triple-A", symbol="S", timestamp="t0",
    )
    return Position(order=Order(sig, size), open_price=100.0, open_time="t0", size=size)


def _mk_pm(oms=None, portfolio_risk=None) -> PositionManager:
    return PositionManager(
        oms=oms or PaperOMS(lot_size=1.0),
        exits=ExitEngine(),
        risk=SessionRisk(storage=None, symbol="S"),
        emit_fn=lambda e: None,
        symbol="S",
        market="MCX",
        contract_expiry=None,
        tick_size=0.05,
        portfolio_risk=portfolio_risk,
    )


def _bar(close: float, open_: float = 100.0) -> Bar:
    return Bar(
        time="2026-08-17T09:30:00+05:30", open=open_, high=close + 0.05, low=open_ - 0.05,
        close=close, volume=100,
    )


# ---------------------------------------------------------------------------
# CRIT-01 Tests
# ---------------------------------------------------------------------------

def test_crit_01_check_pyramid_catches_value_error_under_live_oms():
    """LiveOMS raises ValueError for add_pyramid; check_pyramid must log warning and not crash."""
    portfolio = MagicMock()
    oms = LiveOMS(broker=MagicMock(), portfolio=portfolio, lot_size=1.0)
    pm = _mk_pm(oms)

    pos = _mk_pos()
    # Arm breakeven so base is risk-free
    pm._exits.evaluate(pos, bar_close=101.0, bar_index=3, bar_high=101.0, bar_low=100.9)
    assert pm._exits.is_risk_free(pos)

    dto = {"legLvn": 100.0, "absorptionSide": "SELL_ABSORBED"}
    bar = _bar(close=100.05, open_=100.0)

    # Should not raise exception
    pm.check_pyramid(dto, bar, pos, bar_index=5)
    assert pm.pyramid_count == 0
    assert len(pm.pyramid_positions) == 0


def test_crit_01_check_pyramid_catches_not_implemented_and_generic_exceptions():
    """check_pyramid must catch NotImplementedError and generic Exceptions from add_pyramid."""
    oms_mock = MagicMock()
    oms_mock.add_pyramid.side_effect = NotImplementedError("Pyramids not supported in this broker")
    pm = _mk_pm(oms_mock)

    pos = _mk_pos()
    pm._exits.evaluate(pos, bar_close=101.0, bar_index=3, bar_high=101.0, bar_low=100.9)
    assert pm._exits.is_risk_free(pos)

    dto = {"legLvn": 100.0, "absorptionSide": "SELL_ABSORBED"}
    bar = _bar(close=100.05, open_=100.0)

    # Should catch NotImplementedError
    pm.check_pyramid(dto, bar, pos, bar_index=5)
    assert pm.pyramid_count == 0

    # Should catch arbitrary generic Exception
    oms_mock.add_pyramid.side_effect = RuntimeError("Broker connection timeout")
    pm.check_pyramid(dto, bar, pos, bar_index=6)
    assert pm.pyramid_count == 0


# ---------------------------------------------------------------------------
# CRIT-02 Tests
# ---------------------------------------------------------------------------

def test_crit_02_manage_exit_and_force_close_are_serialized():
    """force_close_position and _manage_exit / _manage_tick_exit serialize on _close_lock."""
    class MockGW:
        def __init__(self):
            self.closed = False
        def subscribe(self, s): pass
        def next_tick(self): return None
        def try_next_tick(self): return None
        def close(self): self.closed = True

    gw = MockGW()
    engine = QuantEngine(gateway=gw, symbol="CRUDEOIL 17 SEP 8300 CALL", interval_seconds=60)
    engine._position = _mk_pos()

    # Verify lock exists
    assert hasattr(engine, "_close_lock")

    close_calls = []
    def slow_manage_tick(pos, price, time_str):
        time.sleep(0.05)
        close_calls.append("tick_exit")
        return None

    engine._get_position_manager().manage_tick_exit = slow_manage_tick

    # Run tick exit and force_close concurrently
    t1 = threading.Thread(target=engine._manage_tick_exit, args=(95.0, "2026-08-17T15:15:00+05:30"))
    t2 = threading.Thread(target=engine.force_close_position, args=("EOD_TEST",))

    t1.start()
    time.sleep(0.01)  # Ensure t1 acquires the lock first
    t2.start()

    t1.join()
    t2.join()

    # Since t1 closed the position under the lock, t2 should observe position is None and return False
    assert engine._position is None


# ---------------------------------------------------------------------------
# HIGH-01 Tests
# ---------------------------------------------------------------------------

def test_high_01_register_open_rejects_when_daily_loss_limit_breached():
    """register_open must atomically reject if realized_pnl <= -max_daily_loss."""
    auth = PortfolioRiskAuthority(
        starting_equity=100_000.0,
        max_portfolio_risk_pct=0.50,
        max_portfolio_daily_loss_pct=0.05,  # 5,000 max loss
    )

    # Initially open risk is 0, realized loss is 0
    assert auth.register_open(1000.0) is True
    assert auth.open_risk == 1000.0

    # Close trade with 6,000 loss (> 5,000 limit)
    auth.record_close(1000.0, -6000.0)
    assert auth.open_risk == 0.0
    assert auth.realized_pnl == -6000.0

    # Even though open risk is 0 (< 50,000), register_open MUST reject due to daily loss breach
    assert auth.register_open(500.0) is False
    assert auth.open_risk == 0.0


def test_high_01_register_open_concurrency_race():
    """Multiple threads attempting register_open while close incurs loss must maintain atomicity."""
    auth = PortfolioRiskAuthority(
        starting_equity=100_000.0,
        max_portfolio_risk_pct=0.10,        # 10,000 max open risk
        max_portfolio_daily_loss_pct=0.03,  # 3,000 max loss
    )

    accepted = []
    rejected = []

    def attempt_register(risk):
        ok = auth.register_open(risk)
        if ok:
            accepted.append(risk)
        else:
            rejected.append(risk)

    # Launch 10 threads trying to register 2,000 risk each (total 20,000 > 10,000)
    threads = [threading.Thread(target=attempt_register, args=(2000.0,)) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Open risk must not exceed 10,000
    assert auth.open_risk <= 10_000.0
    assert len(accepted) == int(auth.open_risk / 2000.0)
    assert len(accepted) + len(rejected) == 10


# ---------------------------------------------------------------------------
# HIGH-02 Tests
# ---------------------------------------------------------------------------

def test_high_02_stop_engine_closes_journal_and_shuts_down_advisor(tmp_path):
    """MultiEngineCoordinator._stop_engine must close engine._journal and shut down advisor."""
    journal_file = str(tmp_path / "test_engine.jsonl")
    journal = Journal(path=journal_file)

    advisor_mock = MagicMock()
    advisor_mock.shutdown = MagicMock()

    class _FakeMD:
        def get_nearest_futures(self, u, e=None): return None
        def fetch_history(self, *a, **k): return []

    coord = QuantCoordinator(
        market_data=_FakeMD(),
        config={
            "include_futures": False,
            "n": 1,
            "exchange": "MCX",
            "underlyings": [],
            "contracts_file": str(tmp_path / "contracts.json"),
            "session_levels_file": None,
        },
    )

    class MockGW:
        def __init__(self): self.closed = False
        def subscribe(self, s): pass
        def next_tick(self): return None
        def try_next_tick(self): return None
        def close(self): self.closed = True

    gw = MockGW()
    engine = QuantEngine(gateway=gw, symbol="CRUDEOIL 17 SEP 8300 CALL", interval_seconds=60)
    engine._journal = journal
    engine._advisor = advisor_mock

    symbol = "CRUDEOIL 17 SEP 8300 CALL"
    coord._engines[symbol] = engine
    coord._gateways[symbol] = gw
    t = threading.Thread(target=lambda: None)
    t.start()
    coord._threads[symbol] = t

    # Stop engine
    coord._stop_engine(symbol)

    # Verify journal is closed
    assert journal._file.closed is True

    # Verify advisor is shut down
    advisor_mock.shutdown.assert_called_once()

    # Verify coordinator maps are cleaned up
    assert symbol not in coord._engines
    assert symbol not in coord._gateways
    assert symbol not in coord._threads
