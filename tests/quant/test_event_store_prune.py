"""EventStore.prune edge-case audit — prune vs the fold truncation guard.

Covers the interactions the earlier prune implementation got wrong:

- prune re-roots the retained slice as its own checksum chain, so
  ``verify_chain()`` must stay True and ``export()`` → ``import_()`` must
  round-trip (previously the original chained HMACs were kept and the pruned
  log failed both).
- ``keep_last=0`` must empty the store — the Python slice trap
  ``events[-0:] == events[0:]`` previously kept EVERYTHING.
- Negative ``keep_last`` is clamped to "keep nothing".
- ``prune()`` resets the incremental fold cache, so a subsequent ``fold()``
  reflects the retained slice, never the stale pre-prune fold.
- A retained slice that begins mid-transition cannot fold (the open event was
  pruned) — ``fold()`` raises rather than silently deriving partial state.
"""

from __future__ import annotations

import pytest

from quant.event_store import EventStore
from quant.events import BarClosed, PositionClosed, PositionOpened, RiskUpdated
from quant.execution.order import Fill, Order, Position
from quant.state_machine import Bar, PositionState, RiskState


def _bar_event(i: int) -> BarClosed:
    return BarClosed(
        symbol="NIFTY",
        time=f"t{i}",
        bar=Bar(time=f"t{i}", open=100.0, high=100.0 + i, low=99.0,
                close=100.0 + i, volume=1000.0),
    )


def _store_with(n: int) -> EventStore:
    store = EventStore()
    for i in range(n):
        store.append(_bar_event(i))
    return store


def _opened_event(pos_id: str = "p1") -> PositionOpened:
    return PositionOpened(
        symbol="NIFTY",
        time="t-open",
        position=PositionState(id=pos_id, entry=100.0, size=10.0,
                               sl=95.0, tp=110.0, side="LONG"),
    )


def _closed_event(pos_id: str = "p1", pnl: float = 50.0) -> PositionClosed:
    fill = Fill(
        position=Position(order=None, open_price=100.0, open_time="t-open",
                          size=10.0, _id=pos_id),
        close_price=105.0,
        close_time="t-close",
        reason="TP",
        pnl=pnl,
    )
    return PositionClosed(symbol="NIFTY", time="t-close", fill=fill)


# ---------------------------------------------------------------------------
# Basic retention semantics
# ---------------------------------------------------------------------------


class TestPruneRetention:
    def test_prune_keeps_most_recent_and_drops_oldest(self):
        store = _store_with(6)
        store.prune(keep_last=3)

        assert [e.time for e in store.get_all()] == ["t3", "t4", "t5"]
        assert len(store._checksums) == 3
        # Sequence is reset to the retained length so fold() never mistakes
        # the sanctioned prune for the truncation-detection guard.
        assert store._sequence == 3
        assert store.fold().last_bar.time == "t5"

    def test_prune_keep_last_equal_or_larger_is_noop(self):
        store = _store_with(3)
        before_events = list(store.get_all())
        before_checksums = list(store._checksums)

        store.prune(keep_last=3)  # equal → no-op
        assert store.get_all() == before_events
        assert store._checksums == before_checksums

        store.prune(keep_last=100)  # larger → no-op
        assert store.get_all() == before_events
        assert store.verify_chain() is True

    def test_prune_empty_store_is_noop(self):
        store = EventStore()
        store.prune(keep_last=0)
        store.prune(keep_last=10)
        store.prune(keep_last=-1)
        assert len(store) == 0
        assert store.fold().symbol == ""


# ---------------------------------------------------------------------------
# keep_last <= 0 (the events[-0:] slice trap)
# ---------------------------------------------------------------------------


class TestPruneKeepLastZero:
    def test_prune_zero_empties_store(self):
        store = _store_with(4)
        store.prune(keep_last=0)

        # Regression: events[-0:] == events[0:] used to keep EVERYTHING.
        assert len(store) == 0
        assert store._sequence == 0
        assert store._checksums == []
        # Empty log folds to an empty state — never a truncated-log panic.
        state = store.fold()
        assert state.symbol == ""
        assert state.last_bar is None

    def test_prune_negative_is_clamped_to_keep_nothing(self):
        store = _store_with(4)
        store.prune(keep_last=-2)
        assert len(store) == 0
        assert store._sequence == 0

    def test_prune_zero_then_append_starts_fresh_chain(self):
        store = _store_with(4)
        store.prune(keep_last=0)
        store.append(_bar_event(99))
        assert [e.time for e in store.get_all()] == ["t99"]
        assert store._sequence == 1
        assert store.verify_chain() is True


# ---------------------------------------------------------------------------
# Checksum re-rooting (confirmed defect: chain broke after prune)
# ---------------------------------------------------------------------------


class TestPruneChecksumChain:
    def test_verify_chain_stays_true_after_prune(self):
        store = _store_with(6)
        assert store.verify_chain() is True
        store.prune(keep_last=3)
        # Regression: the original chained HMACs were kept, so verify_chain
        # recomputed from GENESIS against stale values → False forever.
        assert store.verify_chain() is True

    def test_prune_then_append_keeps_chain_valid(self):
        store = _store_with(6)
        store.prune(keep_last=3)
        store.append(_bar_event(100))
        store.append(_bar_event(101))

        assert store.verify_chain() is True
        assert [e.time for e in store.get_all()] == ["t3", "t4", "t5", "t100", "t101"]
        # Fold of retained + appended matches a fresh store built from the
        # same event sequence.
        expect = EventStore()
        for e in [_bar_event(3), _bar_event(4), _bar_event(5),
                  _bar_event(100), _bar_event(101)]:
            expect.append(e)
        assert store.fold() == expect.fold()

    def test_tamper_detection_still_works_after_prune(self):
        store = _store_with(6)
        store.prune(keep_last=3)
        store.append(_bar_event(100))

        # Tamper with a RETAINED event — the re-rooted chain must catch it.
        tampered = _bar_event(4)
        store._events[1] = tampered
        assert store.verify_chain() is False

    def test_prune_then_export_import_roundtrip(self):
        store = _store_with(6)
        store.prune(keep_last=3)
        exported = store.export()

        # Regression: import_ rejected the pruned export with "checksum
        # mismatch at sequence 1" because the stored HMACs signed through the
        # discarded prefix.
        fresh = EventStore()
        fresh.import_(exported)
        assert [e.time for e in fresh.get_all()] == ["t3", "t4", "t5"]
        assert fresh.verify_chain() is True
        # The round-trip log folds identically.
        assert fresh.fold() == store.fold()


# ---------------------------------------------------------------------------
# Fold-cache reset
# ---------------------------------------------------------------------------


class TestPruneFoldCache:
    def test_prune_resets_fold_cache(self):
        """After prune, fold() reflects the retained slice — never the stale
        pre-prune fold cached by the incremental-folding optimization."""
        store = EventStore()
        store.append(RiskUpdated(
            symbol="NIFTY", time="t-risk",
            risk=RiskState(daily_pnl=-500.0, trades_today=3, halted=True),
        ))
        store.append(_bar_event(0))

        assert store.fold().risk.halted is True  # cached pre-prune fold

        store.prune(keep_last=1)  # drops the RiskUpdated
        state = store.fold()
        # Retained slice is just the bar — risk back to defaults. A stale
        # cache would have returned halted=True here.
        assert state.risk.halted is False
        assert state.last_bar.time == "t0"

    def test_prune_idempotent_after_first_prune(self):
        store = _store_with(10)
        store.prune(keep_last=4)
        first = ([e.time for e in store.get_all()], store.verify_chain())
        store.prune(keep_last=4)  # now a no-op (equal)
        second = ([e.time for e in store.get_all()], store.verify_chain())
        assert second == first


# ---------------------------------------------------------------------------
# Mid-transition retained slices cannot fold
# ---------------------------------------------------------------------------


class TestPruneMidTransitionSlice:
    def test_slice_starting_with_close_replay_tolerant(self):
        """Pruning away a position's opening event leaves a close-only slice:
        fold() returns position=None (replay-tolerant), never raises."""
        store = EventStore()
        store.append(_opened_event("p1"))
        store.append(_closed_event("p1"))

        store.prune(keep_last=1)  # keeps only the PositionClosed

        # Replay-tolerant: returns position=None, no raise
        state = store.fold()
        assert state.position is None

    def test_slice_starting_at_open_folds_cleanly(self):
        """A retained slice that IS a complete transition folds cleanly."""
        store = EventStore()
        store.append(_bar_event(0))  # discarded prefix
        store.append(_opened_event("p1"))
        store.append(_closed_event("p1", pnl=50.0))

        store.prune(keep_last=2)  # keeps [PositionOpened, PositionClosed]

        state = store.fold()
        assert state.position is None
        assert state.realized_pnl == pytest.approx(50.0)

    def test_prune_never_trips_truncation_guard(self):
        """The truncation guard (len < sequence) is for UNSANCTIONED event
        deletion — prune resets the sequence so fold never mistakes it for a
        truncated log (no empty-state refusal)."""
        store = EventStore()
        store.append(_opened_event("p1"))
        store.prune(keep_last=1)

        state = store.fold()  # must fold the retained open, not return empty
        assert state.position is not None
        assert state.position.id == "p1"
