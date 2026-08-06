# tests/quant/runtime/test_runtime.py
"""QuantEngine runtime tests: ticks -> bars -> coordinator -> decision ->
OMS -> exit -> risk -> journal, all driven deterministically by the engine."""

from quant.brokers.gateway import Tick
from quant.brokers.synthetic import SyntheticGateway
from quant.events import SignalApproved
from quant.runtime import QuantEngine


def _ticks():
    """Quiet range bars @100, absorption spike, then rising closes.

    With interval_seconds=1 the aggregator pairs consecutive ticks into a bar
    (each odd tick closes the prior window), so:
      - ticks t0..t299 alternate 99.95/100.05 -> ~150 quiet bars with a 0.1
        range (keeps avg_range > 0 so the zero-range spike passes range_ok)
      - t300/t301 form the absorption spike bar (zero range, 5x volume, 90% buys)
      - t302..t305 are two accumulation bars at POC -> ABSORBING -> ACCUMULATING
      - t306..t309 rise above vwap.upper_1 -> AGGRESSION -> LONG
    """
    out = [Tick(f"t{i}", 99.95 if i % 2 == 0 else 100.05, 10, 6, 4)
           for i in range(300)]
    out.append(Tick("t300", 100.0, 500, 450, 50))
    for i in range(1, 6):
        out.append(Tick(f"t{300 + i}", 100.0, 10, 6, 4))
    for i, price in enumerate([100.3, 100.6, 100.9, 101.2]):
        out.append(Tick(f"t{306 + i}", price, 10, 6, 4))
    return out


def test_engine_emits_signal_event_for_long():
    eng = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1)
    trace = eng.run()
    assert any(isinstance(e, SignalApproved) for e in trace)
    signal_evt = next(e for e in trace if isinstance(e, SignalApproved))
    assert signal_evt.signal.type == "LONG"


def test_engine_trace_is_deterministic():
    t1 = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1).run()
    t2 = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1).run()
    assert t1 == t2
