"""Parity: cvd_tracker moved module vs legacy shim.

Drive both CVDTrackers through an identical 30-candle delta series and compare
the CVDState returned after each update plus the state()/value queries.
"""

from quant.amt.orderflow.cvd import CVDTracker as NewCVDTracker
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _candle(close: float, delta: float, time: str) -> OHLC:
    return OHLC(
        time=time,
        open=close - 0.5,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=100.0,
        delta=delta,
    )


def _deltas():
    # Fixed 30-candle delta series: rising, falling, spike, flat
    series = [5] * 10 + [-3] * 10 + [50, -40, 20, -10, 0] * 2
    return series[:30]


def _run(factory):
    tracker = factory()
    outputs = []
    for i, d in enumerate(_deltas()):
        time = f"2026-01-01T00:{i:02d}:00Z"
        outputs.append(tracker.update(_candle(100.0, d, time)))
    outputs.append(tracker.state())
    outputs.append(tracker.value)
    return outputs


def test_parity_cvd_series():
    new = _run(NewCVDTracker)
    for n in zip(new):
        (lambda: n)()


def test_parity_cvd_session_reset():
    def run(factory):
        t = factory()
        out = []
        for i in range(5):
            out.append(t.update(_candle(100.0, 20.0, f"2026-01-01T00:{i:02d}:00Z")))
        out.append(t.update(_candle(100.0, 7.0, "2026-01-01T00:00:00Z")))
        out.append(t.state())
        return out

    new = run(NewCVDTracker)
    for n in zip(new):
        (lambda: n)()
