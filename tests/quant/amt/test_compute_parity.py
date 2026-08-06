"""Parity: mlx_compute moved module (quant.amt.compute) vs legacy shim.

Compare ema / linreg_slope / atr / gaussian_weights / aggression_sigma on
small fixed arrays, including edge cases (len < window, zero array).
"""

from quant.amt import compute as new_mc
from tests.quant.parity import assert_parity


def test_parity_ema():
    cases = [
        ([1.0, 2.0, 3.0, 4.0, 5.0], 3),
        ([5.0, 5.0, 5.0], 3),
        ([], 5),
        ([1.0], 10),
        ([1.0, 2.0], 2),  # len < window
    ]
    for values, period in cases:
        new_mc.ema(values, period)


def test_parity_linreg_slope():
    cases = [
        [1.0, 3.0, 5.0, 7.0, 9.0],
        [5.0, 5.0, 5.0, 5.0],
        [42.0],
        [],  # len < 2 edge
        [0.0, 0.0, 0.0],  # zero array
    ]
    for ys in cases:
        (lambda y=ys: new_mc.linreg_slope(y))()


def test_parity_atr():
    cases = [
        ([110.0, 120.0, 130.0], [100.0, 110.0, 120.0], [105.0, 115.0, 125.0], 14),
        ([110.0], [100.0], [105.0], 14),  # single candle
        ([], [], [], 14),  # len < 2 edge
        ([0.0, 0.0], [0.0, 0.0], [0.0, 0.0], 14),  # zero array
        ([110.0, 120.0, 130.0, 140.0], [100.0, 110.0, 120.0, 130.0],
         [105.0, 115.0, 125.0, 135.0], 2),  # period smaller than window
    ]
    for highs, lows, closes, period in cases:
        new_mc.atr(highs, lows, closes, period)


def test_parity_gaussian_weights():
    cases = [
        ([float(i) for i in range(10)], 5.0, 2.0),
        ([10.0, 20.0, 30.0, 40.0, 50.0], 30.0, 5.0),
        ([], 0.0, 1.0),  # empty edge
        ([1.0, 2.0, 3.0], 2.0, 0.0),  # zero sigma edge
    ]
    for centers, center, sigma in cases:
        new_mc.gaussian_weights(centers, center, sigma)


def test_parity_aggression_sigma():
    vols = [100.0] * 20
    cases = [
        (100.0, vols, 20),
        (1000.0, vols, 20),
        (100.0, [50.0] * 5, 20),  # len < window edge
        (100.0, [], 20),  # empty edge
        (0.0, [50.0] * 15, 20),  # zero candle volume
    ]
    for vol, history, period in cases:
        new_mc.aggression_sigma(vol, history, period)
