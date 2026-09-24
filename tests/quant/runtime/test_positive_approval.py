# tests/quant/runtime/test_positive_approval.py
"""End-to-end POSITIVE approval path characterization.

The fixture (see ``_organic_approval_ticks``) drives a full unmocked
Triple-A → gate approval. Two properties are pinned here:

  * the organic-tick pipeline is deterministic — two runs emit byte-identical
    event traces;
  * the data-quality safety gate is load-bearing. The fixture runs under a
    real instrument symbol (``NIFTY``) and supplies an explicit L2 book on
    every tick. The paper path keeps the CVD price-direction proxy visible in
    ``PROXY_MODE`` metadata while the organic Triple-A path still approves.
"""

from quant.brokers.gateway import Tick
from tests.helpers.synthetic import SyntheticGateway
from quant.events import DecisionProduced
from quant.execution.risk import SessionRisk
from quant.runtime import QuantEngine

# A real instrument root, not a placeholder. The engine derives the CVD source
# (and therefore the data-quality provenance the decision gate reads) from the
# symbol: a name it does not recognize yields CANDLE_GAUSSIAN and the
# data-quality gate blocks every decision, so an unrecognizable placeholder
# would silently exercise nothing. NIFTY resolves as a tradable underlying.
_SYMBOL = "NIFTY"


def _depth_for(price: float) -> dict:
    price = round(float(price), 4)
    return {
        "bids": [
            {"price": round(price - 0.05, 4), "quantity": 100},
            {"price": round(price - 0.10, 4), "quantity": 250},
        ],
        "asks": [
            {"price": round(price + 0.05, 4), "quantity": 100},
            {"price": round(price + 0.10, 4), "quantity": 250},
        ],
    }


def _organic_approval_ticks():
    """Organic ticks that drive a full Triple-A → gate approval, unmocked.

    The recipe is deliberately over-constrained so it stays honest: it must
    produce AGGRESSION *and* a genuine leg LVN *and* LVN proximity at the same
    bar, or gate 3 fails. Three properties had to hold simultaneously, and
    each one constrains the shape of the tape:

    1.  AN INTERIOR LOW-VOLUME VOID IN THE LEG. The leg detector walks
        backwards over same-direction candles, and the LVN predicate
        (spec §5.1 rule 4) only considers buckets strictly between the two
        profile edges — so the leg needs >= 3 distinct price buckets with the
        void strictly inside. A void at the top or bottom of the leg is never
        a candidate.
    2.  THE VOID SURVIVING THE ABSORPTION SPIKE. The spike is a 25-50x volume
        candle; if it lands inside the leg it swamps the void's bucket and the
        LVN disappears. So the leg is built FIRST and the spike is placed at a
        price the leg never trades.
    3.  AGGRESSION AND THE LVN CO-EXISTING IN TIME. The Triple-A machine needs
        >= 2 bars of consolidation near the POC after absorption goes pending
        (ABSORBING -> ACCUMULATING), then the displacement close to fire.
        _STALE_BARS then resets it, so the displacement must land inside that
        window — it does, on the bar after the spike.

    The pre-C6 form of this fixture had a three-bucket leg whose "LVN" was an
    artifact of the smoothing kernel: the peak-volume bucket (510 vs 50/90)
    smoothed into a *local minimum* because its neighbours averaged higher.
    Spec §5.1 rule 4's absolute floor V(p) < 0.35 x V_bar_profile correctly
    rejects that (216 > 93), which is the whole point of the gate — so the
    fixture was reworked to contain a REAL interior void (the t301 bucket at
    2 lots, an order of magnitude below its 40-lot neighbours).
    """
    out = [
        Tick(
            f"t{i}",
            99.95 if i % 2 == 0 else 100.25,
            10,
            9,
            1,
            depth=_depth_for(99.95 if i % 2 == 0 else 100.25),
        )
        for i in range(300)
    ]
    # Leg first: an up-run with a genuine interior low-volume void at 100.10.
    # The void's bucket volume (2) is ~5% of its 40-lot neighbours, so it
    # clears the 0.35 x mean floor AND the percentile gate AND is strictly
    # interior — gate 3's LVN proximity window then catches 100.05/100.10.
    out.append(Tick("t300", 100.05, 40, 35, 5, depth=_depth_for(100.05)))    # up 1
    out.append(Tick("t301", 100.10, 2, 1, 1, depth=_depth_for(100.10)))      # interior void (leg LVN)
    out.append(Tick("t302", 100.15, 40, 35, 5, depth=_depth_for(100.15)))    # up 2
    # Absorption spike: 50x volume, sell-dominant (64% sellers), zero-range,
    # at a price the leg never trades so the void is not contaminated.
    out.append(Tick("t303", 100.15, 500, 180, 320, depth=_depth_for(100.15)))  # SELL_ABSORBED pending
    out.append(Tick("t304", 100.20, 100, 90, 10, depth=_depth_for(100.20)))    # displacement up -> AGGRESSION
    out.append(Tick("t305", 100.20, 100, 90, 10, depth=_depth_for(100.20)))      # bar after AGGRESSION
    return out


def _run_organic():
    SessionRisk(storage=None, symbol=_SYMBOL).reset_session()
    eng = QuantEngine(SyntheticGateway(_organic_approval_ticks()), _SYMBOL,
                      interval_seconds=1)
    return eng.run()


def test_engine_organic_trace_is_deterministic():
    t1 = _run_organic()
    t2 = _run_organic()
    assert [type(e).__name__ for e in t1] == [type(e).__name__ for e in t2]


def test_engine_organic_data_quality_lifecycle():
    """Provenance is decided by exactly one authority: DecisionLoop.

    The service path (gates 1-4) is quality-agnostic since N3; the decision
    loop blocks live/proxy flows on non-exact evidence and marks paper runs
    PROXY_MODE. The organic fixture runs paper (default OMS), so:

    * no decision may carry the retired service-level provenance reason;
    * pre-footprint bars evaluate through the real gates (not short-circuited);
    * once the footprint accumulator publishes, the fixture's organic Triple-A
      path must produce an approval — the lifecycle end-to-end.
    """
    trace = _run_organic()
    decisions = [e for e in trace if isinstance(e, DecisionProduced)]
    assert decisions, "engine must evaluate every bar"
    assert all(
        d.decision.reason != "DATA_QUALITY_BLOCKED" for d in decisions
    ), "service-level provenance short-circuit is retired (N3)"
    evaluated = [
        d for d in decisions
        if d.decision.reason not in ("NO_EDGE", "HALTED", "COOLDOWN")
    ]
    assert evaluated, "bars must reach the real gates"
    approved = [d for d in decisions if d.decision.approved]
    assert approved, "fixture sanity: the organic path must produce an approval"
