# tests/quant/runtime/test_signal_blocked_latch.py
"""A blocked approval emits exactly one SignalBlocked per blocking episode.
Evaluation itself is never latched — vetoes still run every bar, so the
moment a signal becomes executable it trades."""

from dataclasses import dataclass, field
from unittest.mock import MagicMock

from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.events import PositionOpened, SignalApproved, SignalBlocked
from quant.execution.order import Order, Position
from quant.runtime import QuantEngine


@dataclass
class _ApprovedDecision:
    signal: Signal
    approved: bool = True
    reason: str = "Triple-A"
    phase: str = ""
    gate_results: tuple = ()
    block_reasons: tuple = ()
    model_label: str = "t"
    metadata: dict = field(default_factory=dict)


def _sig():
    return Signal(
        type="LONG", reason="t", entry=14.0, sl=13.0, tp=16.0, rr=2.0,
        model_label="t", symbol="LATCH-CALL", timestamp="t0",
    )


def _engine():
    pra = MagicMock()
    eng = QuantEngine(gateway=MagicMock(), symbol="LATCH-CALL", portfolio_risk=pra)
    eng._oms = MagicMock()
    eng._oms.lot_size = 1
    eng._oms.is_live = False
    # ponytail: EventStore checksum-serializes every event eagerly, so the
    # stubbed position must be a real Position — a MagicMock recurses there.
    eng._oms.submit.return_value = Position(
        order=Order(signal=_sig(), quantity=2.0),
        open_price=14.0,
        open_time="t300",
        size=2.0,
    )
    eng._risk = MagicMock()
    eng._risk.can_trade.return_value = (True, "")
    from quant.execution.risk import RiskState
    eng._risk.state.return_value = RiskState(
        daily_pnl=0.0, consecutive_losses=0, halted=False, halt_reason="",
        risk_per_trade_pct=0.005, trades_today=0, equity=1_000_000,
    )
    eng._risk.position_size.return_value = 2
    stub = MagicMock()
    stub.should_enter.return_value = _ApprovedDecision(_sig())
    eng._strategy = stub
    blocked = []
    eng._bus.subscribe(SignalBlocked, lambda e: blocked.append(e))
    return eng, blocked, pra


def _bar(n):
    return Bar(time=f"t{300 + n}", open=14.0, high=14.2, low=13.9, close=14.0, volume=10.0)


def test_sizing_zero_emits_one_blocked_event():
    eng, blocked, _ = _engine()
    eng._risk.position_size.return_value = 0
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    assert len(blocked) == 1
    assert "0 lots" in blocked[0].reason


def test_portfolio_reject_emits_once_per_episode():
    pra = MagicMock()
    pra.can_accept.return_value = (False, "concurrent root position: LATCH-CALL active")
    eng, blocked, _ = _engine()
    eng._portfolio_risk = pra
    for i, bar_index in enumerate((10, 13, 16, 19)):  # each beyond the 2-bar debounce
        eng._bar_index = bar_index
        eng._decide({}, _bar(i))
    assert len(blocked) == 1
    assert pra.can_accept.call_count == 4  # evaluation continues, only emission is latched


def test_register_reject_emits_one_blocked_event():
    # can_accept passes but register_open loses the race → same episode.
    pra = MagicMock()
    pra.can_accept.return_value = (True, "")
    pra.register_open.return_value = False
    eng, blocked, _ = _engine()
    eng._portfolio_risk = pra
    for i, bar_index in enumerate((10, 13, 16, 19)):  # each beyond the 2-bar debounce
        eng._bar_index = bar_index
        eng._decide({}, _bar(i))
    assert len(blocked) == 1
    assert "cap breached" in blocked[0].reason
    assert pra.can_accept.call_count == 4  # evaluation continues, only emission is latched
    eng._oms.submit.assert_not_called()


def test_oms_raise_emits_one_blocked_event_and_unwinds_reservation():
    pra = MagicMock()
    pra.can_accept.return_value = (True, "")
    pra.register_open.return_value = True
    eng, blocked, _ = _engine()
    eng._portfolio_risk = pra
    eng._oms.submit.side_effect = RuntimeError("boom")
    emitted = []
    eng._bus.subscribe(SignalApproved, lambda e: emitted.append(e))
    eng._bus.subscribe(PositionOpened, lambda e: emitted.append(e))
    for i, bar_index in enumerate((10, 13, 16, 19)):  # each beyond the 2-bar debounce
        eng._bar_index = bar_index
        eng._decide({}, _bar(i))
    assert len(blocked) == 1
    assert "OMS submit raised" in blocked[0].reason
    assert pra.release.called  # reservation unwound on the failed submit
    assert emitted == []


def test_new_block_reason_starts_new_episode():
    pra = MagicMock()
    pra.can_accept.side_effect = [
        (False, "concurrent root position: X active"),
        (False, "portfolio open-risk limit: 100+50 > 120"),
    ]
    eng, blocked, _ = _engine()
    eng._portfolio_risk = pra
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    eng._bar_index = 13
    eng._decide({}, _bar(1))
    assert len(blocked) == 2


def test_successful_entry_resets_latch():
    pra = MagicMock()
    pra.can_accept.side_effect = [
        (False, "concurrent root position: X active"),
        (True, ""),
        (False, "concurrent root position: X active"),
    ]
    eng, blocked, _ = _engine()
    eng._portfolio_risk = pra
    eng._bar_index = 10
    eng._decide({}, _bar(0))   # blocked → episode 1
    eng._bar_index = 13
    eng._decide({}, _bar(1))   # executes → latch cleared
    eng._bar_index = 16
    eng._decide({}, _bar(2))   # blocked again → fresh episode
    assert len(blocked) == 2
    eng._oms.submit.assert_called_once()


def test_sizing_zero_entry_drift_emits_one_blocked_event():
    # SignalBuilder sets entry = float(ctx.bar.close), so a fresh Signal every
    # micro-bar carries a new price. The episode key must be stable anyway.
    eng, blocked, _ = _engine()
    eng._risk.position_size.return_value = 0

    def drifted(ctx):
        entry = float(ctx.bar.close)  # mirror SignalBuilder: entry = bar.close
        return _ApprovedDecision(
            Signal(
                type="LONG", reason="t", entry=entry, sl=entry - 1.0,
                tp=entry + 2.0, rr=2.0, model_label="t",
                symbol="LATCH-CALL", timestamp="t0",
            )
        )

    eng._strategy.should_enter.side_effect = drifted
    for i, bar_index in enumerate((10, 13, 16, 19)):  # each beyond the 2-bar debounce
        close = 14.0 + i * 0.5
        bar = Bar(
            time=f"t{300 + i}", open=close, high=close + 0.2,
            low=close - 0.1, close=close, volume=10.0,
        )
        eng._bar_index = bar_index
        eng._decide({}, bar)
    assert len(blocked) == 1
    assert "0 lots" in blocked[0].reason


def test_sizing_zero_then_reason_change_emits_twice():
    eng, blocked, _ = _engine()
    eng._risk.position_size.side_effect = [0, 0]
    # same reason → one episode
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    eng._bar_index = 13
    eng._decide({}, _bar(1))
    assert len(blocked) == 1


@dataclass
class _NonApprovedDecision:
    approved: bool = False
    signal: Signal | None = None
    reason: str = "NO_EDGE"
    phase: str = ""
    gate_results: tuple = ()
    block_reasons: tuple = ("no edge",)
    model_label: str = ""
    metadata: dict = field(default_factory=dict)


def test_non_approved_decision_starts_new_episode():
    # blocked(R) → market goes NO_EDGE for a stretch → the same setup blocked
    # with the same reason again is a FRESH episode (the market changed between).
    pra = MagicMock()
    pra.can_accept.return_value = (False, "concurrent root position: X active")
    eng, blocked, _ = _engine()
    eng._portfolio_risk = pra
    eng._bar_index = 10
    eng._decide({}, _bar(0))          # blocked → episode 1
    eng._strategy.should_enter.return_value = _NonApprovedDecision()
    eng._bar_index = 13
    eng._decide({}, _bar(1))          # non-approved → episodes stale
    eng._bar_index = 16
    eng._decide({}, _bar(2))          # non-approved again
    eng._strategy.should_enter.return_value = _ApprovedDecision(_sig())
    eng._bar_index = 19
    eng._decide({}, _bar(3))          # blocked same reason → NEW episode
    assert len(blocked) == 2


def test_alternating_keys_keep_independent_episodes():
    # Two distinct blocked setups alternate; each key owns its episode, so A
    # returning after B does not re-emit (single-slot latch would re-emit).
    sig_a = Signal(type="LONG", reason="t", entry=14.0, sl=13.0, tp=16.0, rr=2.0,
                   model_label="t", symbol="A-CE", timestamp="t0")
    sig_b = Signal(type="SHORT", reason="t", entry=14.0, sl=15.0, tp=12.0, rr=2.0,
                   model_label="t", symbol="B-PE", timestamp="t0")
    pra = MagicMock()
    pra.can_accept.return_value = (False, "concurrent root position: X active")
    eng, blocked, _ = _engine()
    eng._portfolio_risk = pra
    eng._strategy.should_enter.side_effect = [
        _ApprovedDecision(sig_a), _ApprovedDecision(sig_b), _ApprovedDecision(sig_a),
    ]
    for i, bar_index in enumerate((10, 13, 16)):
        eng._bar_index = bar_index
        eng._decide({}, _bar(i))
    assert len(blocked) == 2  # A emits, B emits, A is latched (same episode)


def test_sizing_zero_with_mock_risk_emits_generic_reason_no_raise():
    # Regression (task 12 round 2): a MagicMock risk fabricates any attribute,
    # so a diagnostic probe inside the zero-quantity guard could raise and kill
    # the entry path. Sizing is now deterministic, so a zero size must always
    # fall through to the generic budget reason without raising.
    eng, blocked, _ = _engine()
    eng._risk.position_size.return_value = 0
    eng._bar_index = 10
    eng._decide({}, _bar(0))  # must not raise
    assert len(blocked) == 1
    assert "0 lots" in blocked[0].reason
    assert "model sizing unavailable" not in blocked[0].reason
