# tests/quant/runtime/test_positive_approval.py
"""End-to-end POSITIVE approval path: organic ticks -> analyzer -> Triple-A
AGGRESSION -> gates 1..4 -> SignalApproved -> PositionOpened fill.

Since ae0d832 rebuilt the Triple-A decision core, every pre-existing
SignalApproved assertion in the runtime suite was NEGATIVE ("never approve").
This test closes that gap: it proves the engine can still approve and fill
from synthetic-but-organic market data flowing through the real pipeline
(no mocks, no injected contexts).

Fixture recipe (each ingredient is load-bearing):
  - ~150 quiet bars alternating 99.95/100.05 with 9:1 buy volume -> builds a
    positive CVD slope so gate 3's direction guard tolerates one moderate
    sell-spike.
  - One zero-range 50x-volume spike with mild SELL dominance (180/320) ->
    AbsorptionDetector flags a tight-range high-volume candle as
    SELL_ABSORBED pending (delta < 0 -> sellers absorbed -> bullish).
  - Two displacement bars closing above the absorb candle's high within the
    detector's 2-bar window -> validated SELL_ABSORBED pulse ->
    TripleAMachine enters AGGRESSION LONG.
  - Continued rise keeps context consistent through gates 1 (phase
    permission), 2, 3 (CVD guard), and 4 (RR) to approval and fill.

Characterization note: values were tuned against current behavior on
purpose. WS2-A's build() extraction must keep this green unchanged.
"""

from quant.brokers.gateway import Tick
from tests.helpers.synthetic import SyntheticGateway
from quant.events import DecisionProduced, PositionOpened, SignalApproved
from quant.execution.risk import SessionRisk
from quant.runtime import QuantEngine


def _organic_approval_ticks():
    out = [Tick(f"t{i}", 99.95 if i % 2 == 0 else 100.05, 10, 9, 1)
           for i in range(300)]
    out.append(Tick("t300", 100.0, 500, 180, 320))   # absorption spike (SELL_ABSORBED)
    out.append(Tick("t301", 100.0, 10, 6, 4))        # close the spike bar
    out.append(Tick("t302", 100.4, 20, 14, 6))       # displacement up (validates)
    out.append(Tick("t303", 100.6, 20, 14, 6))
    for i, price in enumerate([100.8, 101.0, 101.2]):
        out.append(Tick(f"t{304 + i}", price, 10, 9, 1))
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


def test_approval_is_triple_a_with_no_block_reasons():
    trace = _run_organic()
    decisions = [e for e in trace if isinstance(e, DecisionProduced)]
    triple_a = [d for d in decisions if d.decision.approved]
    assert len(triple_a) == 1
    d = triple_a[0]
    assert d.decision.reason == "Triple-A"
    assert list(d.decision.block_reasons) == []
    assert d.decision.signal is not None
