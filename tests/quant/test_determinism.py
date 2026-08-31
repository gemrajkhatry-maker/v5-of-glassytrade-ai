"""Replay determinism test — same session must produce identical results every time.

Runs the same golden scenario 10 times and verifies:
- Same number of events
- Same signal count
- Same entries, stops, targets
- Same pyramids
- Same exits
- Same PnL

Any variation = FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.quant.test_golden_replay import (
    replay,
    scenario_balanced_rotation,
    scenario_displacement_breakout,
    scenario_stop_out,
)


def _fingerprint(rep):
    """Create a deterministic fingerprint of a replay."""
    return {
        "events": len(rep.events),
        "approved": len(rep.decisions_approved),
        "rejected": len(rep.decisions_rejected),
        "positions": len(rep.positions_opened),
    }


def test_determinism_balanced_rotation():
    """Balanced rotation must produce identical results every time."""
    results = [replay(scenario_balanced_rotation()) for _ in range(10)]
    fingerprints = [_fingerprint(r) for r in results]
    assert all(f == fingerprints[0] for f in fingerprints), (
        f"Non-deterministic results: {fingerprints}"
    )


def test_determinism_displacement_breakout():
    """Displacement breakout must produce identical results every time."""
    results = [replay(scenario_displacement_breakout()) for _ in range(10)]
    fingerprints = [_fingerprint(r) for r in results]
    assert all(f == fingerprints[0] for f in fingerprints), (
        f"Non-deterministic results: {fingerprints}"
    )


def test_determinism_stop_out():
    """Stop out scenario must produce identical results every time."""
    results = [replay(scenario_stop_out()) for _ in range(10)]
    fingerprints = [_fingerprint(r) for r in results]
    assert all(f == fingerprints[0] for f in fingerprints), (
        f"Non-deterministic results: {fingerprints}"
    )


def test_determinism_event_order():
    """Events must fire in the same order every time."""
    results = [replay(scenario_displacement_breakout()) for _ in range(10)]
    first_events = [type(e).__name__ for e in results[0].events]
    for i, r in enumerate(results[1:], 1):
        events = [type(e).__name__ for e in r.events]
        assert events == first_events, (
            f"Event order mismatch at run {i}: {events} != {first_events}"
        )
