# tests/quant/runtime/test_pyramid_accounting_parity.py
"""Spy test: PortfolioRiskAuthority must realize EACH pyramid add-on's fill
pnl EXACTLY ONCE, across all three natural close sequences:

  A. bar-path full close (tiered TP partial -> later close) with 2 pyramids
  B. tick-path TP1/TP2 partials -> later close, with 1 pyramid
  C. OPPOSING_SIGNAL thesis-flip close, with 1 pyramid

The E11 loop in PositionManager._execute_full_close pairs every add-on with
its OWN fill pnl and OWN reserved risk_i — that is the canonical ledger. If
any OTHER site (e.g. the runtime's post-close reserve release) also feeds the
aggregate last_pyramid_pnl into record_close, the realized multiset breaks:
this spy counts occurrences.
"""

from types import SimpleNamespace

import pytest

from quant.bars import Bar
from quant.brokers.gateway import Tick
from quant.decision.signal_builder import Signal
from quant.events import PositionClosed, PositionReduced
from quant.execution.portfolio_risk import PortfolioRiskAuthority
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway

_BASE_EPOCH = 1_700_000_000


class SpiedPortfolioRisk(PortfolioRiskAuthority):
    """Captures every record_close(risk, pnl) call."""

    def __init__(self):
        super().__init__(starting_equity=1_000_000)
        self.realized_calls = []

    def record_close(self, risk_rupees: float, pnl: float) -> None:
        self.realized_calls.append((float(risk_rupees), float(pnl)))
        super().record_close(risk_rupees, pnl)


def _signal(side="LONG", entry=100.0, sl=90.0, tp=120.0):
    return Signal(type=side, reason="test", entry=entry, sl=sl, tp=tp,
                  rr=2.0, model_label="Triple-A", symbol="TEST",
                  timestamp=str(_BASE_EPOCH))


def _spy_engine(auth, ticks=None, interval_seconds=300):
    eng = QuantEngine(
        SyntheticGateway(list(ticks or [])), "TEST",
        interval_seconds=interval_seconds, portfolio_risk=auth,
    )
    return eng


def _inject_long_with_pyramids(eng, auth, pyr_specs):
    """Open base LONG (size 4 @100, sl90 tp120, R=400) plus hand-built
    add-ons wired exactly like the live pyramid flow would: registered in
    the portfolio authority AND keyed in the PM's per-pyramid risk map."""
    base = eng._oms.submit(_signal(), 4.0)
    # Set position in both state and position manager
    from quant.transitions import _position_to_state
    eng.state = eng.state.with_position(_position_to_state(base))
    pm = eng._get_position_manager()
    pm.current_position = base
    eng._entry_bar_index = 0
    base_risk = (100.0 - 90.0) * 4.0
    assert auth.register_open(base_risk)
    eng._open_trade_risk = base_risk
    for i, (entry_px, size) in enumerate(pyr_specs, start=1):
        pyr = eng._oms.add_pyramid(
            base=base, entry_price=entry_px,
            new_sl=min(100.2, entry_px - 0.3), size=size,
            time=f"t{i}", pyramid_level=i,
        )
        pm.pyramid_positions.append(pyr)
        pm.pyramid_count += 1
        r_i = (100.0 - 95.0) * size
        assert auth.register_open(r_i)
        pm._pyramid_open_risk[pyr._id] = r_i
    return base, pm


def _pnls(calls):
    return [p for _, p in calls]


# ---------------------------------------------------------------------------
# A. Natural BAR-path close (TP1 partial -> BREAKEVEN close), 2 pyramids
# ---------------------------------------------------------------------------

def test_natural_bar_close_books_each_addon_once():
    auth = SpiedPortfolioRisk()
    eng = _spy_engine(auth)
    base, _pm = _inject_long_with_pyramids(
        eng, auth, [(100.5, 2.0), (101.0, 1.0)],
    )
    assert abs(base.size) == 4.0

    # Bar 1: high clips TP (120) -> Rule 4 TP1 partial closes half @ 120.
    eng._on_bar_closed(Bar(time="b1", open=100.0, high=121.0, low=99.5,
                           close=120.5, volume=10))
    assert eng.state.position is not None
    # Bar 2: low pierces the BE floor armed at TP1 -> full close of runner +
    # both add-ons at bar.close = 95.
    eng._on_bar_closed(Bar(time="b2", open=96.0, high=97.0, low=94.0,
                           close=95.0, volume=10))
    assert eng.state.position is None

    # Exact realized-pnl multiset: TP1 partial (@120, half), runner residual
    # close (@95, remaining half), and each add-on's OWN fill pnl ONCE.
    expected = sorted([
        (120.0 - 100.0) * 2.0,   # TP1 partial fill
        (95.0 - 100.0) * 2.0,    # base runner full close
        (95.0 - 100.5) * 2.0,    # pyramid 1 fill
        (95.0 - 101.0) * 1.0,    # pyramid 2 fill
    ])
    actual = sorted(p for p in _pnls(auth.realized_calls))
    assert actual == pytest.approx(expected), (
        f"realized pnl multiset drifted: {actual} vs {expected}"
    )
    assert auth.open_risk == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# B. Tick-path partials (TP1 touch -> TP2 touch) then breach, 1 pyramid
# ---------------------------------------------------------------------------

def test_tick_path_close_books_each_addon_once():
    auth = SpiedPortfolioRisk()
    ticks = [
        Tick(str(_BASE_EPOCH), 100.0, 10, 5, 5),
        Tick(str(_BASE_EPOCH + 30), 121.0, 10, 10, 0),   # TP1 tick touch
        Tick(str(_BASE_EPOCH + 60), 145.0, 10, 10, 0),   # >= tp2 (140)
        Tick(str(_BASE_EPOCH + 90), 80.0, 10, 0, 10),    # below BE floor
    ]
    eng = _spy_engine(auth, ticks)
    _inject_long_with_pyramids(eng, auth, [(100.5, 2.0)])

    eng.run()

    assert eng.state.position is None
    reduced = [e for e in eng.events if isinstance(e, PositionReduced)]
    closed = [e for e in eng.events if isinstance(e, PositionClosed)]
    assert len(reduced) == 2 and closed  # sanity: partial, partial, full

    expected = sorted([
        (121.0 - 100.0) * 2.0,   # tick TP1 partial
        (145.0 - 100.0) * 1.0,   # tick TP2 partial (half of remainder)
        (80.0 - 100.0) * 1.0,    # base runner full close
        (80.0 - 100.5) * 2.0,    # pyramid fill — exactly once
    ])
    actual = sorted(p for p in _pnls(auth.realized_calls))
    assert actual == pytest.approx(expected), (
        f"tick-path realized multiset drifted: {actual} vs {expected}"
    )
    assert auth.open_risk == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# C. OPPOSING_SIGNAL thesis-flip close, 1 pyramid
# ---------------------------------------------------------------------------

def test_thesis_flip_close_books_each_addon_once():
    auth = SpiedPortfolioRisk()
    eng = _spy_engine(auth)
    _inject_long_with_pyramids(eng, auth, [(100.5, 2.0)])

    short_sig = _signal(side="SHORT")
    stub_decision = SimpleNamespace(
        approved=True, signal=short_sig, gate_results=[], reason="APPROVED",
        phase="", block_reasons=[], model_label="",
    )
    eng._decision_service = SimpleNamespace(
        evaluate=lambda ctx, allow_positioned=False: stub_decision,
    )
    eng._build_context = lambda bar, amt_dto, cooldown_sec: object()

    eng._check_thesis_flip(
        {"marketState": "BALANCED"},
        Bar(time="f1", open=100.0, high=100.5, low=99.5, close=99.75,
            volume=10),
    )

    assert eng.state.position is None, "contrary approval must flatten"
    closes = [e for e in eng.events if isinstance(e, PositionClosed)]
    assert closes[-1].fill.reason == "OPPOSING_SIGNAL"

    expected = sorted([
        (99.75 - 100.0) * 4.0,   # base close
        (99.75 - 100.5) * 2.0,   # pyramid fill — exactly once
    ])
    actual = sorted(p for p in _pnls(auth.realized_calls))
    assert actual == pytest.approx(expected), (
        f"flip-path realized multiset drifted: {actual} vs {expected}"
    )
    assert auth.open_risk == pytest.approx(0.0)
