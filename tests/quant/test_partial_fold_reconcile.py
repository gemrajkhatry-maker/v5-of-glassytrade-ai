# tests/quant/test_partial_fold_reconcile.py
"""Phase 1: single position truth.

Covers the three Phase-1 fixes end to end:

1. ``apply_event`` folds ``PositionReduced`` (tiered-TP partials) so the
   event-store fold and ``engine.state`` carry the REDUCED size — previously
   they kept the original full size while PositionManager (execution truth)
   held the survivor, and periodic_reconcile could not see the drift.
2. ``periodic_reconcile`` compares the cached state against the
   PositionManager book (execution authority) — a book-vs-state divergence
   is now reported instead of being invisible.
3. ``startup_reconcile`` no longer clobbers a position restored from storage
   with an empty event-store fold (the JSONL journal is not replayed into
   the in-memory EventStore on restart).
"""
import pytest

from quant.brokers.gateway import Tick
from quant.decision.signal_builder import Signal
from quant.events import PositionOpened, PositionReduced
from quant.execution.order import Fill, Position
from quant.execution.portfolio_risk import PortfolioRiskAuthority
from quant.runtime import QuantEngine
from quant.state_machine import EngineState, PositionState
from quant.transitions import apply_event, _position_to_state
from tests.helpers.synthetic import SyntheticGateway


def _make_signal(symbol="TEST", side="LONG", entry=100.0, sl=90.0, tp=120.0):
    return Signal(
        type=side,
        reason="Triple-A setup",
        entry=entry,
        sl=sl,
        tp=tp,
        rr=2.0,
        model_label="Triple-A",
        symbol=symbol,
        timestamp="1700000000",
    )


def _make_engine():
    gw = SyntheticGateway([Tick("1700000000", 100.0, 10, 5, 5)])
    return QuantEngine(gw, "TEST", interval_seconds=300)


def _opened_position(size=4.0):
    sig = _make_signal()
    return Position(
        order=__import__("quant.execution.order", fromlist=["Order"]).Order(
            signal=sig, quantity=abs(size)
        ),
        open_price=sig.entry,
        open_time=sig.timestamp,
        size=size,
    )


def _partial_reduce(position, fraction=0.5, price=110.0):
    """Mirror PaperOMS.close_partial: build fill + remaining with same _id."""
    closed_size = position.size * fraction
    remaining_size = position.size * (1.0 - fraction)
    partial_pnl = (price - position.open_price) * closed_size
    fill_position = Position(
        order=position.order,
        open_price=position.open_price,
        open_time=position.open_time,
        size=closed_size,
        realized_pnl=partial_pnl,
        pyramid_level=position.pyramid_level,
        is_pyramid=position.is_pyramid,
    )
    fill = Fill(
        position=fill_position,
        close_price=price,
        close_time="1700000060",
        reason="TP1",
        pnl=partial_pnl,
    )
    remaining = Position(
        order=position.order,
        open_price=position.open_price,
        open_time=position.open_time,
        size=remaining_size,
        pyramid_level=position.pyramid_level,
        is_pyramid=position.is_pyramid,
        _id=position._id,
    )
    return fill, remaining


# ---------------------------------------------------------------------------
# 1. apply_event folds PositionReduced
# ---------------------------------------------------------------------------


class TestPositionReducedFold:
    def test_fold_reduces_position_size(self):
        """PositionReduced shrinks the open position's size, keeping its id."""
        pos = _opened_position(size=4.0)
        fill, remaining = _partial_reduce(pos, fraction=0.5)
        state = EngineState(symbol="TEST")
        state = apply_event(state, PositionOpened(symbol="TEST", time="t0", position=pos))
        state = apply_event(
            state, PositionReduced(symbol="TEST", time="t1", fill=fill, remaining=remaining)
        )
        assert state.position is not None
        assert state.position.size == pytest.approx(2.0)
        assert state.position.id == pos._id

    def test_fold_ignores_unknown_reduce_id(self):
        """A reduce for a foreign id is a no-op (replay must never raise)."""
        pos = _opened_position(size=4.0)
        fill, remaining = _partial_reduce(pos, fraction=0.5)
        state = EngineState(symbol="TEST")
        state = apply_event(state, PositionOpened(symbol="TEST", time="t0", position=pos))
        foreign = Position(
            order=pos.order,
            open_price=pos.open_price,
            open_time=pos.open_time,
            size=2.0,
            _id="foreign-id",
        )
        state = apply_event(
            state,
            PositionReduced(symbol="TEST", time="t1", fill=fill, remaining=foreign),
        )
        assert state.position.size == pytest.approx(4.0)

    def test_fold_reduces_pyramid(self):
        """A pyramid add-on's partial reduce updates that pyramid entry."""
        from dataclasses import replace

        base = _opened_position(size=4.0)
        pyr = replace(_opened_position(size=2.0), is_pyramid=True, pyramid_level=1)
        state = EngineState(symbol="TEST")
        state = apply_event(state, PositionOpened(symbol="TEST", time="t0", position=base))
        state = apply_event(state, PositionOpened(symbol="TEST", time="t1", position=pyr))
        fill, remaining = _partial_reduce(pyr, fraction=0.5)
        state = apply_event(
            state, PositionReduced(symbol="TEST", time="t2", fill=fill, remaining=remaining)
        )
        assert state.position.size == pytest.approx(4.0)
        assert len(state.pyramids) == 1
        assert state.pyramids[0].size == pytest.approx(1.0)

    def test_full_open_reduce_close_sequence_folds_correctly(self):
        """The complete partial lifecycle folds to a flat state."""
        from quant.events import PositionClosed
        from quant.execution.order import Fill as ExecFill

        pos = _opened_position(size=4.0)
        fill, remaining = _partial_reduce(pos, fraction=0.5)
        state = EngineState(symbol="TEST")
        state = apply_event(state, PositionOpened(symbol="TEST", time="t0", position=pos))
        state = apply_event(
            state, PositionReduced(symbol="TEST", time="t1", fill=fill, remaining=remaining)
        )
        close_fill = ExecFill(
            position=remaining,
            close_price=105.0,
            close_time="t2",
            reason="SESSION_CLOSE",
            pnl=(105.0 - pos.open_price) * remaining.size,
        )
        state = apply_event(state, PositionClosed(symbol="TEST", time="t2", fill=close_fill))
        assert state.position is None
        assert state.pyramids == ()


# ---------------------------------------------------------------------------
# 2. Engine state + periodic reconcile vs PositionManager
# ---------------------------------------------------------------------------


class TestEngineStateAndReconcile:
    def _open_then_partial(self, eng, position):
        """Open via event AND pm book, then reduce both — the healthy state."""
        eng._emit(PositionOpened(symbol="TEST", time="t0", position=position))
        pm = eng._get_position_manager()
        pm.current_position = position
        fill, remaining = _partial_reduce(position, fraction=0.5)
        eng._emit(
            PositionReduced(symbol="TEST", time="t1", fill=fill, remaining=remaining)
        )
        pm.current_position = remaining
        return remaining

    def test_engine_state_tracks_partial_size(self):
        """engine.state.position.size matches the reduced runner after a partial."""
        eng = _make_engine()
        position = _opened_position(size=4.0)
        remaining = self._open_then_partial(eng, position)
        assert eng.state.position is not None
        assert eng.state.position.size == pytest.approx(2.0)
        # The event-store fold agrees with the cached state.
        assert eng.event_store.fold().position.size == pytest.approx(2.0)

    def test_periodic_reconcile_clean_when_book_matches(self):
        """No drift when the pm book and the folded state agree."""
        eng = _make_engine()
        position = _opened_position(size=4.0)
        remaining = self._open_then_partial(eng, position)
        result = eng.periodic_reconcile()
        assert result.has_drift is False, result.discrepancies

    def test_periodic_reconcile_detects_book_drift(self):
        """A pm book that diverges from state (e.g. missed event) is reported."""
        eng = _make_engine()
        position = _opened_position(size=4.0)
        remaining = self._open_then_partial(eng, position)
        # Tamper the execution book: it holds the FULL size while state holds
        # the reduced runner (the pre-fix PositionReduced staleness).
        pm = eng._get_position_manager()
        pm.current_position = position
        result = eng.periodic_reconcile()
        assert result.has_drift is True
        assert any(
            "position_manager_size=4.0" in d for d in result.discrepancies
        ), result.discrepancies

    def test_periodic_reconcile_detects_missing_book_position(self):
        """State holding a position the execution book lost is drift."""
        eng = _make_engine()
        position = _opened_position(size=4.0)
        self._open_then_partial(eng, position)
        pm = eng._get_position_manager()
        pm.current_position = None
        result = eng.periodic_reconcile()
        assert result.has_drift is True


# ---------------------------------------------------------------------------
# 3. startup_reconcile preserves the restored book
# ---------------------------------------------------------------------------


class TestStartupReconcileRestore:
    def test_startup_reconcile_adopts_restored_position(self):
        """A restored position survives startup_reconcile (empty event store)."""
        eng = _make_engine()
        position = _opened_position(size=4.0)
        eng.restore_position(position)
        assert eng.state.position is not None  # restore set the book
        eng.startup_reconcile()
        assert eng.state.position is not None, (
            "startup_reconcile clobbered the restored position with an empty fold"
        )
        assert eng.state.position.id == position._id

    def test_startup_reconcile_flat_when_no_book(self):
        """No book + empty store -> stays flat, no exceptions."""
        eng = _make_engine()
        eng.startup_reconcile()
        assert eng.state.position is None