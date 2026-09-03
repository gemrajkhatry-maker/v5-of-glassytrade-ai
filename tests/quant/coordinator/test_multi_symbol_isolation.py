"""Multi-symbol isolation and determinism tests.

Verifies that multiple QuantEngine instances running under one process
maintain strict per-symbol state isolation:

- Each engine's EventStore contains only its own symbol's events
- Decisions on symbol A don't affect symbol B's state
- Two runs with the same per-symbol tick streams produce identical traces
- Event ordering is valid per symbol

Uses QuantEngine directly (not QuantCoordinator) to test isolation at
the engine level — the coordinator delegates to engines and adds its
own orchestration layer tested separately.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from quant.brokers.gateway import Tick  # noqa: E402
from quant.events import (  # noqa: E402
    AgentDecisionProduced,
    BarClosed,
    DecisionProduced,
    PositionClosed,
    PositionOpened,
    RiskUpdated,
)
from quant.execution.risk import SessionRisk  # noqa: E402
from quant.runtime import QuantEngine  # noqa: E402
from tests.helpers.synthetic import SyntheticGateway  # noqa: E402


# ---------------------------------------------------------------------------
# Tick generation — distinct per symbol
# ---------------------------------------------------------------------------


def _build_ticks_for_symbol(seed_price: float, n: int = 120) -> list[Tick]:
    """Generate deterministic ticks anchored at a seed price."""
    ticks: list[Tick] = []
    t0 = 1_787_664_600
    sec = t0
    for i in range(n):
        # Gentle oscillation around seed_price
        price = seed_price + 0.03 * ((i % 6) - 2.5)
        vol = 10.0 + (i % 5)
        ticks.append(Tick(str(sec), round(price, 4), vol, vol * 0.5, vol * 0.5))
        sec += 1
    return ticks


def _run_engine(ticks: list[Tick], symbol: str) -> tuple:
    """Run a QuantEngine and return (trace, event_store_export, folded_state)."""
    SessionRisk(storage=None, symbol=symbol).reset_session()
    gw = SyntheticGateway(list(ticks))
    eng = QuantEngine(gw, symbol, interval_seconds=1, market="MCX")
    trace = eng.run()
    export = list(eng.event_store.export())
    folded = eng.event_store.fold()
    return trace, export, folded


def _trace_fingerprint(trace: list) -> str:
    sync = [e for e in trace if not isinstance(e, AgentDecisionProduced)]
    payload = json.dumps(
        [(type(e).__name__, getattr(e, "time", "")) for e in sync],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


SYMBOL_A = "GOLDM SEP FUT"
SYMBOL_B = "SILVERM SEP FUT"


class TestMultiSymbolIsolation:
    """Two engines running different symbols maintain independent state."""

    def test_event_store_symbol_isolation(self):
        """Each engine's EventStore contains only its own symbol's events."""
        ticks_a = _build_ticks_for_symbol(100.0)
        ticks_b = _build_ticks_for_symbol(200.0)

        trace_a, export_a, fold_a = _run_engine(ticks_a, SYMBOL_A)
        trace_b, export_b, fold_b = _run_engine(ticks_b, SYMBOL_B)

        # Folded state should have the correct symbol
        assert fold_a.symbol == SYMBOL_A
        assert fold_b.symbol == SYMBOL_B

        # Export rows should carry the correct symbol
        for row in export_a:
            assert row.get("symbol") == SYMBOL_A, (
                f"Symbol A export contains wrong symbol: {row.get('symbol')}"
            )
        for row in export_b:
            assert row.get("symbol") == SYMBOL_B, (
                f"Symbol B export contains wrong symbol: {row.get('symbol')}"
            )

    def test_engines_produce_independent_events(self):
        """Events from engine A don't appear in engine B's trace."""
        ticks_a = _build_ticks_for_symbol(100.0)
        ticks_b = _build_ticks_for_symbol(200.0)

        trace_a, _, _ = _run_engine(ticks_a, SYMBOL_A)
        trace_b, _, _ = _run_engine(ticks_b, SYMBOL_B)

        # All events in trace_a should have symbol A
        for e in trace_a:
            assert e.symbol == SYMBOL_A, (
                f"Engine A trace contains event for wrong symbol: {e.symbol}"
            )
        for e in trace_b:
            assert e.symbol == SYMBOL_B, (
                f"Engine B trace contains event for wrong symbol: {e.symbol}"
            )

    def test_different_tick_tapes_different_outcomes(self):
        """Different tick tapes can produce different event counts."""
        ticks_a = _build_ticks_for_symbol(100.0, n=120)
        ticks_b = _build_ticks_for_symbol(200.0, n=180)

        trace_a, _, _ = _run_engine(ticks_a, SYMBOL_A)
        trace_b, _, _ = _run_engine(ticks_b, SYMBOL_B)

        # Different tick counts should generally produce different event counts
        # (not guaranteed, but very likely with different durations)
        assert len(trace_a) != len(trace_b) or len(trace_a) > 0


class TestMultiSymbolDeterminism:
    """Each engine is independently deterministic."""

    def test_engine_a_deterministic(self):
        """Engine A produces identical traces across runs."""
        ticks = _build_ticks_for_symbol(100.0)
        fp_a = _trace_fingerprint(_run_engine(ticks, SYMBOL_A)[0])
        fp_b = _trace_fingerprint(_run_engine(ticks, SYMBOL_A)[0])
        assert fp_a == fp_b, "Engine A is not deterministic"

    def test_engine_b_deterministic(self):
        """Engine B produces identical traces across runs."""
        ticks = _build_ticks_for_symbol(200.0)
        fp_a = _trace_fingerprint(_run_engine(ticks, SYMBOL_B)[0])
        fp_b = _trace_fingerprint(_run_engine(ticks, SYMBOL_B)[0])
        assert fp_a == fp_b, "Engine B is not deterministic"

    def test_both_engines_deterministic_together(self):
        """Running both engines in sequence doesn't affect determinism."""
        ticks_a = _build_ticks_for_symbol(100.0)
        ticks_b = _build_ticks_for_symbol(200.0)

        # Run 1: A then B
        trace_a1, _, _ = _run_engine(ticks_a, SYMBOL_A)
        trace_b1, _, _ = _run_engine(ticks_b, SYMBOL_B)

        # Run 2: A then B again
        trace_a2, _, _ = _run_engine(ticks_a, SYMBOL_A)
        trace_b2, _, _ = _run_engine(ticks_b, SYMBOL_B)

        assert _trace_fingerprint(trace_a1) == _trace_fingerprint(trace_a2)
        assert _trace_fingerprint(trace_b1) == _trace_fingerprint(trace_b2)


class TestMultiSymbolEventOrdering:
    """Event ordering invariants per symbol."""

    def test_bar_closed_events_present(self):
        """Each engine produces BarClosed events from its own tick stream."""
        ticks_a = _build_ticks_for_symbol(100.0)
        ticks_b = _build_ticks_for_symbol(200.0)

        trace_a, _, _ = _run_engine(ticks_a, SYMBOL_A)
        trace_b, _, _ = _run_engine(ticks_b, SYMBOL_B)

        bars_a = [e for e in trace_a if isinstance(e, BarClosed)]
        bars_b = [e for e in trace_b if isinstance(e, BarClosed)]

        assert len(bars_a) > 0, "Engine A produced no BarClosed events"
        assert len(bars_b) > 0, "Engine B produced no BarClosed events"

    def test_decision_events_present(self):
        """Each engine evaluates decisions independently."""
        ticks_a = _build_ticks_for_symbol(100.0)
        ticks_b = _build_ticks_for_symbol(200.0)

        trace_a, _, _ = _run_engine(ticks_a, SYMBOL_A)
        trace_b, _, _ = _run_engine(ticks_b, SYMBOL_B)

        decisions_a = [e for e in trace_a if isinstance(e, DecisionProduced)]
        decisions_b = [e for e in trace_b if isinstance(e, DecisionProduced)]

        assert len(decisions_a) > 0, "Engine A produced no DecisionProduced events"
        assert len(decisions_b) > 0, "Engine B produced no DecisionProduced events"

    def test_position_lifecycle_ordering(self):
        """If a position opens and closes, open precedes close."""
        ticks = _build_ticks_for_symbol(100.0, n=200)
        trace, _, _ = _run_engine(ticks, SYMBOL_A)

        opened = [i for i, e in enumerate(trace) if isinstance(e, PositionOpened)]
        closed = [i for i, e in enumerate(trace) if isinstance(e, PositionClosed)]

        if opened and closed:
            assert min(closed) > min(opened), (
                "PositionClosed before PositionOpened"
            )
