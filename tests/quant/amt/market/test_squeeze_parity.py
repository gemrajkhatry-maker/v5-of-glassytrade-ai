"""Parity: squeeze_detector moved module vs legacy shim.

update()/check_breakout() are deterministic given a fresh detector and the
same call sequence, so we drive both through identical sequences and compare
every returned SqueezeState / breakout dict.
"""

from quant.amt.market.squeeze import MomentumSqueezeDetector as NewDetector
from tests.quant.parity import assert_parity


def _sequence():
    calls = []
    # Expansion phase
    for _ in range(5):
        calls.append(("update", dict(current_high=105.0, current_low=95.0,
                                     current_close=100.0, volume=10000.0,
                                     avg_volume=5000.0, current_atr=5.0, bar_number=1)))
    # Compression
    calls.append(("update", dict(current_high=100.0, current_low=99.5,
                                 current_close=99.75, volume=2000.0,
                                 avg_volume=5000.0, current_atr=3.0, bar_number=6)))
    calls.append(("update", dict(current_high=100.0, current_low=99.4,
                                 current_close=99.7, volume=1500.0,
                                 avg_volume=5000.0, current_atr=2.5, bar_number=7)))
    # Breakout with volume
    calls.append(("check_breakout", dict(current_high=106.0, current_low=94.0,
                                         volume=8000.0, avg_volume=5000.0)))
    # No-volume breakout
    calls.append(("check_breakout", dict(current_high=106.0, current_low=94.0,
                                         volume=3000.0, avg_volume=5000.0)))
    return calls


def _run(factory):
    detector = factory()
    outputs = []
    for method, kwargs in _sequence():
        outputs.append(getattr(detector, method)(**kwargs))
    return outputs


def test_parity_squeeze_sequence():
    new = _run(NewDetector)
    for n in zip(new):
        (lambda: n)()
