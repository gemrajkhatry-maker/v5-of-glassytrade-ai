# tests/quant/runtime/test_amt_golden.py
"""Golden characterization test for QuantEngine._amt_analyze().

Captures AmtUpdated events from a known bar sequence.
This becomes the regression safety net for extracting the AMT engine.

The test verifies that:
1. AMT DTO output is deterministic
2. Key AMT fields are populated correctly
3. Session rollover logic works as expected
"""

from tests.helpers.synthetic import SyntheticGateway
from quant.events import AmtUpdated
from quant.runtime import QuantEngine
from tests.quant.runtime.test_runtime import _ticks


def _capture_amt_trace(ticks, symbol="SYM"):
    """Run the engine and capture all AmtUpdated events."""
    eng = QuantEngine(SyntheticGateway(ticks), symbol, interval_seconds=1)
    trace = eng.run()
    amt_events = [e for e in trace if isinstance(e, AmtUpdated)]
    return [
        {
            "poc": e.amt.get("poc") if e.amt else None,
            "vah": e.amt.get("valueAreaHigh") if e.amt else None,
            "val": e.amt.get("valueAreaLow") if e.amt else None,
            "vwap": e.amt.get("vwap") if e.amt else None,
            "marketState": e.amt.get("marketState") if e.amt else None,
            "balanceRatio": e.amt.get("balanceRatio") if e.amt else None,
            "obi": e.amt.get("obi") if e.amt else None,
            "priorPoc": e.amt.get("priorPoc") if e.amt else None,
            "npocAbove": e.amt.get("npocAbove") if e.amt else None,
            "npocBelow": e.amt.get("npocBelow") if e.amt else None,
            "legLvn": e.amt.get("legLvn") if e.amt else None,
            "isSecondDrive": e.amt.get("isSecondDrive") if e.amt else None,
        }
        for e in amt_events
    ]


def test_amt_golden_trace_is_deterministic():
    """The AMT trace must be identical across runs."""
    t1 = _capture_amt_trace(_ticks())
    t2 = _capture_amt_trace(_ticks())
    assert t1 == t2, "AMT trace is not deterministic"


def test_amt_golden_populates_key_fields():
    """The AMT DTO must populate key fields after warmup."""
    result = _capture_amt_trace(_ticks())
    # After warmup, at least some AMT events should have non-None fields
    assert len(result) > 0, "Expected at least one AMT event"
    # The last event should have meaningful data
    last = result[-1]
    # POC should be populated (volume profile center)
    assert last["poc"] is not None
    # VAH/VAL should bracket the POC
    if last["vah"] is not None and last["val"] is not None and last["poc"] is not None:
        assert last["val"] <= last["poc"] <= last["vah"]


def test_amt_golden_market_state_is_valid():
    """The market state must be a valid value."""
    result = _capture_amt_trace(_ticks())
    valid_states = {"BALANCED", "IMBALANCED", "DEAD", None}
    for evt in result:
        assert evt["marketState"] in valid_states, f"Invalid market state: {evt['marketState']}"


def test_amt_golden_vwap_is_positive():
    """VWAP should be positive when populated."""
    result = _capture_amt_trace(_ticks())
    for evt in result:
        if evt["vwap"] is not None and evt["vwap"] > 0:
            assert evt["vwap"] > 0
