# tests/quant/runtime/test_decide_golden.py
"""Golden characterization test for QuantEngine._decide().

Captures the full DecisionProduced event trace from a seeded engine run
with known inputs. This becomes the regression safety net for all subsequent
extractions from the runtime god-module.

The test verifies that:
1. The decision trace is deterministic (same ticks -> same decisions)
2. The DecisionContext fields are populated correctly
3. The gate evaluation produces the expected results
"""

import json
from pathlib import Path

from tests.helpers.synthetic import SyntheticGateway
from quant.events import DecisionProduced, SignalApproved
from quant.runtime import QuantEngine
from tests.quant.runtime.test_runtime import _ticks, _short_ticks


GOLDEN_DIR = Path(__file__).parent / "golden"


def _capture_decide_trace(ticks, symbol="SYM"):
    """Run the engine and capture all DecisionProduced events."""
    from quant.execution.risk import SessionRisk
    from quant.strategies.amt_scalping import AmtScalpingStrategy
    SessionRisk(storage=None, symbol=symbol).reset_session()
    eng = QuantEngine(
        SyntheticGateway(ticks),
        symbol,
        interval_seconds=1,
        strategy=AmtScalpingStrategy(),
    )
    trace = eng.run()
    decisions = [e for e in trace if isinstance(e, DecisionProduced)]
    signals = [e for e in trace if isinstance(e, SignalApproved)]
    return {
        "decisions": [
            {
                "approved": d.decision.approved,
                "reason": d.decision.reason,
                "phase": d.decision.phase,
                "model_label": d.decision.model_label,
                "block_reasons": list(d.decision.block_reasons),
                "signal_type": d.decision.signal.type if d.decision.signal else None,
                "signal_entry": d.decision.signal.entry if d.decision.signal else None,
                "signal_sl": d.decision.signal.sl if d.decision.signal else None,
                "signal_tp": d.decision.signal.tp if d.decision.signal else None,
                "signal_rr": d.decision.signal.rr if d.decision.signal else None,
            }
            for d in decisions
        ],
        "signals": [
            {
                "type": s.signal.type,
                "entry": s.signal.entry,
                "sl": s.signal.sl,
                "tp": s.signal.tp,
                "rr": s.signal.rr,
                "reason": s.signal.reason,
            }
            for s in signals
        ],
    }


def test_decide_golden_long_trace_is_deterministic():
    """The LONG decision trace must be identical across runs."""
    t1 = _capture_decide_trace(_ticks())
    t2 = _capture_decide_trace(_ticks())
    assert t1 == t2, "Decision trace is not deterministic"


def test_decide_golden_short_trace_is_deterministic():
    """The SHORT decision trace must be identical across runs."""
    t1 = _capture_decide_trace(_short_ticks())
    t2 = _capture_decide_trace(_short_ticks())
    assert t1 == t2, "Decision trace is not deterministic"


def test_decide_golden_long_does_not_enter_without_triple_a():
    """Imbalance continuation is not an entry. This tape used to be a
    false-confidence golden that passed via Gate 3 Path A.3."""
    result = _capture_decide_trace(_ticks())
    assert result["signals"] == []
    assert not any(d["approved"] for d in result["decisions"])


def test_decide_golden_short_does_not_enter_without_triple_a():
    result = _capture_decide_trace(_short_ticks())
    assert result["signals"] == []
    assert not any(d["approved"] for d in result["decisions"])


def test_decide_golden_long_has_expected_gate_results():
    """Decisions fire, but Gate 3 does not pass without AGGRESSION."""
    result = _capture_decide_trace(_ticks())
    assert result["decisions"], "engine must still evaluate gates"
    assert not any(d["approved"] for d in result["decisions"])


def test_decide_golden_matches_committed_snapshot():
    """Re-audit: the file-writing test above only ever overwrote
    golden/decide_long.json and asserted the write succeeded — nothing ever
    read the file back, so a real behavior regression in the decision
    pipeline could silently drift the recorded trace with no test catching
    it (false confidence: the "golden" file was write-only). This test
    diffs a fresh trace against the committed snapshot and fails loudly on
    any drift. Update the snapshot deliberately (rerun the recorder script
    below) when a change is an intentional behavior change."""
    snapshot_path = GOLDEN_DIR / "decide_long.json"
    with open(snapshot_path) as f:
        expected = json.load(f)

    actual = _capture_decide_trace(_ticks())

    assert actual == expected, (
        "decide_long.json golden trace drifted from actual QuantEngine "
        "behavior. If this is an intentional change, regenerate the "
        "snapshot with _record_golden_snapshot() and review the diff."
    )


def _record_golden_snapshot():
    """Regenerate golden/decide_long.json after a deliberate behavior
    change. Not collected by pytest (no test_ prefix) — run manually:
    python -c "from tests.quant.runtime.test_decide_golden import _record_golden_snapshot as f; f()"
    """
    result = _capture_decide_trace(_ticks())
    snapshot_path = GOLDEN_DIR / "decide_long.json"
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w") as f:
        json.dump(result, f, indent=2)
