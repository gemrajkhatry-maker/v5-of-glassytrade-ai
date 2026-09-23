"""EventStore export/prune replay integration tests.

Validates the full round-trip:

  QuantEngine → EventStore → export_to_jsonl → import_ → fold → state parity

Ensures that EventStore primitives (export, import, prune) correctly
preserve and reconstruct trading state, enabling backtest/replay
consistency with live trading.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from quant.brokers.gateway import Tick  # noqa: E402
from quant.event_store import EventStore  # noqa: E402
from quant.execution.risk import SessionRisk  # noqa: E402
from quant.runtime import QuantEngine  # noqa: E402
from tests.helpers.synthetic import SyntheticGateway  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_ticks(n: int = 120, seed_price: float = 100.0) -> list[Tick]:
    """Generate deterministic ticks."""
    ticks: list[Tick] = []
    t0 = 1_787_664_600
    sec = t0
    for i in range(n):
        price = seed_price + 0.03 * ((i % 6) - 2.5)
        vol = 10.0 + (i % 5)
        ticks.append(Tick(str(sec), round(price, 4), vol, vol * 0.5, vol * 0.5))
        sec += 1
    return ticks


def _run_engine(ticks: list[Tick], symbol: str = "GOLDM SEP FUT") -> QuantEngine:
    """Run a QuantEngine and return it (with EventStore intact)."""
    SessionRisk(storage=None, symbol=symbol).reset_session()
    gw = SyntheticGateway(list(ticks))
    eng = QuantEngine(gw, symbol, interval_seconds=1, market="MCX")
    eng.run()
    return eng


# ---------------------------------------------------------------------------
# Export → Import round-trip tests
# ---------------------------------------------------------------------------


class TestExportImportRoundTrip:
    """EventStore.export() → EventStore.import_() preserves state."""

    def test_export_import_preserves_event_count(self):
        """Imported EventStore has the same number of events."""
        eng = _run_engine(_build_ticks())
        export = list(eng.event_store.export())
        assert len(export) > 0, "Source EventStore is empty"

        fresh = EventStore()
        fresh.import_(export)
        assert len(fresh) == len(eng.event_store)

    def test_export_import_preserves_fold_state(self):
        """Fold on imported store matches fold on original."""
        eng = _run_engine(_build_ticks())
        export = list(eng.event_store.export())

        fresh = EventStore()
        fresh.import_(export)

        orig_fold = eng.event_store.fold()
        new_fold = fresh.fold()

        assert orig_fold.symbol == new_fold.symbol
        assert orig_fold.sequence == new_fold.sequence
        assert (orig_fold.position is None) == (new_fold.position is None)
        if orig_fold.position is not None:
            assert orig_fold.position.id == new_fold.position.id
            assert orig_fold.position.entry == new_fold.position.entry
            assert orig_fold.position.size == new_fold.position.size
        assert orig_fold.realized_pnl == new_fold.realized_pnl
        assert orig_fold.risk == new_fold.risk

    def test_export_import_preserves_verify_chain(self):
        """Imported EventStore passes checksum verification."""
        eng = _run_engine(_build_ticks())
        export = list(eng.event_store.export())

        fresh = EventStore()
        fresh.import_(export)
        assert fresh.verify_chain(), "Imported EventStore checksum chain broken"


# ---------------------------------------------------------------------------
# JSONL streaming round-trip tests
# ---------------------------------------------------------------------------


class TestJsonlRoundTrip:
    """export_to_jsonl → read back → import_ preserves state."""

    def test_jsonl_export_import_roundtrip(self):
        """JSONL file export → import produces identical fold."""
        eng = _run_engine(_build_ticks())
        orig_fold = eng.event_store.fold()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            rows_written = eng.event_store.export_to_jsonl(path)
            assert rows_written > 0

            # Read back
            with open(path, "r") as fh:
                rows = [json.loads(line) for line in fh if line.strip()]

            assert len(rows) == rows_written

            # Import into fresh store
            fresh = EventStore()
            fresh.import_(rows)

            new_fold = fresh.fold()
            assert orig_fold.symbol == new_fold.symbol
            assert orig_fold.sequence == new_fold.sequence
            assert (orig_fold.position is None) == (new_fold.position is None)
            assert orig_fold.realized_pnl == new_fold.realized_pnl
        finally:
            Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Prune → Import tests
# ---------------------------------------------------------------------------


class TestPruneImport:
    """Prune then export → import preserves partial state."""

    def test_prune_then_export_import(self):
        """After pruning, the retained slice round-trips correctly."""
        eng = _run_engine(_build_ticks(n=200))
        original_count = len(eng.event_store)
        assert original_count > 10, "Need enough events to prune meaningfully"

        # Prune to last 10 events
        keep = 10
        eng.event_store.prune(keep_last=keep)
        assert len(eng.event_store) == keep

        # Export the pruned store
        export = list(eng.event_store.export())
        assert len(export) == keep

        # Import into fresh store
        fresh = EventStore()
        fresh.import_(export)
        assert len(fresh) == keep

        # Chain verification passes on pruned+imported store
        assert fresh.verify_chain()

    def test_prune_preserves_chain_integrity(self):
        """After prune, verify_chain still passes."""
        eng = _run_engine(_build_ticks(n=150))
        eng.event_store.prune(keep_last=20)
        assert eng.event_store.verify_chain()

    def test_prune_resets_fold_cache(self):
        """After prune, fold() re-derives from retained events only."""
        eng = _run_engine(_build_ticks(n=150))
        # Fold before prune (caches state)
        _ = eng.event_store.fold()
        # Prune
        eng.event_store.prune(keep_last=5)
        # Fold after prune should work (derives from retained slice)
        folded = eng.event_store.fold()
        # The fold may or may not have a position (depends on which events retained)
        # but it should not crash
        assert folded.symbol == "GOLDM SEP FUT" or folded.symbol == ""


# ---------------------------------------------------------------------------
# Full replay parity test
# ---------------------------------------------------------------------------


class TestReplayParity:
    """Run engine → export → import → verify state parity."""

    def test_full_replay_parity(self):
        """The complete export → import → fold pipeline preserves all state."""
        ticks = _build_ticks(n=200)
        eng = _run_engine(ticks)

        # Original state
        orig_export = list(eng.event_store.export())
        orig_fold = eng.event_store.fold()
        orig_chain_valid = eng.event_store.verify_chain()

        # Replay into fresh store
        fresh = EventStore()
        fresh.import_(orig_export)

        # Verify parity
        assert fresh.verify_chain() == orig_chain_valid
        new_fold = fresh.fold()

        assert orig_fold.symbol == new_fold.symbol
        assert orig_fold.sequence == new_fold.sequence
        assert orig_fold.realized_pnl == new_fold.realized_pnl
        assert orig_fold.risk == new_fold.risk

        # Position parity
        assert (orig_fold.position is None) == (new_fold.position is None)
        if orig_fold.position is not None:
            assert orig_fold.position.id == new_fold.position.id
            assert orig_fold.position.entry == new_fold.position.entry
            assert orig_fold.position.side == new_fold.position.side
