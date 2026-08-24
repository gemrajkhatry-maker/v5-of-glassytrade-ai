# tests/quant/runtime/test_runtime.py
"""QuantEngine runtime tests: ticks -> bars -> coordinator -> decision ->
OMS -> exit -> risk -> journal, all driven deterministically by the engine."""

import pytest

from quant.brokers.gateway import Tick
from quant.brokers.synthetic import SyntheticGateway
from quant.contracts.entities import Signal
from quant.contracts.enums import SetupType, SignalType, Source
from quant.decision.decision_service import QuantDecision
from quant.decision.signal_builder import MAX_POSITION_QUANTITY
from quant.events import PositionOpened, SignalApproved
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
    eng = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1, stream_id="test:SYM")
    trace = eng.run()
    assert any(isinstance(e, SignalApproved) for e in trace)
    signal_evt = next(e for e in trace if isinstance(e, SignalApproved))
    assert signal_evt.signal.type == SignalType.BUY


def test_engine_trace_is_deterministic():
    t1 = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1, stream_id="deterministic:SYM").run()
    t2 = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1, stream_id="deterministic:SYM").run()
    assert t1 == t2


class _FixedDecisionService:
    """Returns a canned approved decision for the thin/healthy stop cases."""

    def __init__(self, signal: Signal) -> None:
        self._signal = signal

    def evaluate(self, ctx):
        return QuantDecision(True, self._signal, "Triple-A", "AGGRESSION", ())


def _run_with_signal(signal: Signal):
    eng = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1,
                      stream_id="test:SYM", strategy=_FixedDecisionService(signal))
    trace = eng.run()
    return next(e for e in trace if isinstance(e, PositionOpened))


def _signal(entry, sl, tp, rr):
    return Signal.create(
        type=SignalType.BUY,
        price=entry,
        reason="test",
        stop_loss=sl,
        take_profit=tp,
        timestamp="t",
        setup=SetupType.TREND_MODEL,
        source=Source.LLM,
        metadata={"quant_rr": rr, "confidence": 0.7},
    )


def _thin_stop_signal() -> Signal:
    # 0.02% stop -> SessionRisk would size 50_000 units; clamp caps at 1000.
    return _signal(100.0, 99.98, 100.06, 3.0)


def _healthy_stop_signal() -> Signal:
    # 3% stop -> 100k * 1% / 3.0 = 333 units, under the ceiling.
    return _signal(100.0, 97.0, 106.0, 2.0)


def test_runtime_clamps_thin_stop_quantity_to_max():
    opened = _run_with_signal(_thin_stop_signal())
    assert opened.position.order.quantity == MAX_POSITION_QUANTITY


def test_runtime_leaves_healthy_stop_quantity_unclamped():
    opened = _run_with_signal(_healthy_stop_signal())
    assert opened.position.order.quantity == pytest.approx(100_000.0 * 0.01 / 3.0)
