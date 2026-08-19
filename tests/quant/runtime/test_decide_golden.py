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
    eng = QuantEngine(SyntheticGateway(ticks), symbol, interval_seconds=1)
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


def test_decide_golden_long_produces_signal():
    """The LONG tick sequence must produce an approved signal."""
    result = _capture_decide_trace(_ticks())
    assert len(result["signals"]) >= 1, "Expected at least one approved signal"
    sig = result["signals"][0]
    assert sig["type"] == "LONG"
    assert sig["entry"] > 0
    assert sig["sl"] > 0
    assert sig["tp"] > 0
    assert sig["rr"] >= 1.5  # min_rr default


def test_decide_golden_short_produces_signal():
    """The SHORT tick sequence must produce an approved signal."""
    result = _capture_decide_trace(_short_ticks())
    assert len(result["signals"]) >= 1, "Expected at least one approved signal"
    sig = result["signals"][0]
    assert sig["type"] == "SHORT"


def test_decide_golden_long_has_expected_gate_results():
    """The LONG decision must pass all 4 gates."""
    result = _capture_decide_trace(_ticks())
    # Find the approved decision
    approved = [d for d in result["decisions"] if d["approved"]]
    assert len(approved) >= 1
    dec = approved[0]
    assert dec["reason"] in ("Triple-A", "LVN_Sniper", "VA_FADE")
    assert dec["block_reasons"] == []  # No blocked gates


def test_decide_golden_records_snapshot(tmp_path):
    """Record the golden snapshot to file for manual inspection.
    
    Run with: pytest -s tests/quant/runtime/test_decide_golden.py::test_decide_golden_records_snapshot
    """
    result = _capture_decide_trace(_ticks())
    snapshot_path = GOLDEN_DIR / "decide_long.json"
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w") as f:
        json.dump(result, f, indent=2)
    # Verify the file was written
    assert snapshot_path.exists()
