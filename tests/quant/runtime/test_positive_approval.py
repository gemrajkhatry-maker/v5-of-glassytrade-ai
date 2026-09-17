# tests/quant/runtime/test_positive_approval.py
"""End-to-end POSITIVE approval path: organic ticks -> analyzer -> evidence
setup (LVN Sniper) / Triple-A AGGRESSION -> gates 1..4 -> SignalApproved ->
PositionOpened fill.

Since ae0d832 rebuilt the Triple-A decision core, every pre-existing
SignalApproved assertion in the runtime suite was NEGATIVE ("never approve").
This test closes that gap: it proves the engine can still approve and fill
from synthetic-but-organic market data flowing through the real pipeline
(no mocks, no injected contexts).

Fixture recipe (each ingredient is load-bearing):
  - ~150 quiet bars alternating 99.95/100.25 with 9:1 buy volume -> builds a
    positive CVD slope so gate 3's direction guard tolerates one moderate
    sell-spike, and seeds the leg profile with a thin 100.0 gap between the
    low/high quiet prices.
  - One zero-range 50x-volume spike at 100.0 with mild SELL dominance
    (180/320) -> AbsorptionDetector flags a tight-range high-volume candle as
    SELL_ABSORBED pending (delta < 0 -> sellers absorbed -> bullish).
  - A displacement bar closing above the absorb candle's high AND on the leg
    LVN (100.0) within gate 3's 5-tick proximity window -> validated
    SELL_ABSORBED pulse -> TripleAMachine enters AGGRESSION LONG and the
    absorption+LVN evidence qualifies. The evidence path runs before the
    raw Triple-A path, so the emitted model label is ``LVN_Sniper``.
  - One extra tick closes that approval bar (the aggregator closes bar N on
    the first tick of bar N+1), ending the run at the fill. Deliberately no
    further closes: the determinism/hot-path probes compare raw event
    dataclasses, and a post-fill TRAIL_RATCHET StopMoved carries a
    per-run position uuid that is not part of the behavior under test.

Characterization note: values were tuned against current behavior on
purpose. WS2-A's build() extraction must keep this green unchanged.
"""

from quant.brokers.gateway import Tick
from tests.helpers.synthetic import SyntheticGateway
from quant.events import DecisionProduced, PositionOpened, SignalApproved
from quant.execution.risk import SessionRisk
from quant.runtime import QuantEngine


def _organic_approval_ticks():
    out = [Tick(f"t{i}", 99.95 if i % 2 == 0 else 100.25, 10, 9, 1)
           for i in range(300)]
    out.append(Tick("t300", 100.0, 500, 180, 320))   # absorption spike (SELL_ABSORBED)
    out.append(Tick("t301", 100.0, 10, 6, 4))        # close the spike bar
    out.append(Tick("t302", 100.25, 30, 20, 10))     # displacement up, closes @ leg LVN 100.0
    out.append(Tick("t303", 100.4, 20, 14, 6))       # closes t302's bar -> approval + fill
    return out


def _run_organic():
    from datetime import date
    SessionRisk(storage=None, symbol="SYM").reset_session()
    eng = QuantEngine(SyntheticGateway(_organic_approval_ticks()), "SYM",
                      interval_seconds=1)
    return eng.run()


def test_engine_approves_and_fills_from_organic_data():
    trace = _run_organic()
    approvals = [e for e in trace if isinstance(e, SignalApproved)]
    assert len(approvals) == 1, f"expected exactly one organic approval, got {len(approvals)}"
    sig = approvals[0].signal
    assert sig.type == "LONG"
    assert sig.entry > 100.0
    opens = [e for e in trace if isinstance(e, PositionOpened)]
    assert len(opens) == 1, "approval must produce exactly one real fill"


def test_approval_has_named_model_with_no_block_reasons():
    trace = _run_organic()
    decisions = [e for e in trace if isinstance(e, DecisionProduced)]
    approved = [d for d in decisions if d.decision.approved]
    assert len(approved) == 1
    d = approved[0]
    # The absorption+leg-LVN evidence path is evaluated before the raw
    # Triple-A AGGRESSION path, so the ACTUAL model label is LVN_Sniper.
    assert d.decision.reason == "LVN_Sniper"
    assert d.decision.model_label == "LVN_Sniper"
    assert list(d.decision.block_reasons) == []
    assert d.decision.signal is not None
