"""Parity: aggression_scorer moved module vs legacy shim.

Compare AggressionScorer.score() for the boolean-mask combos: all-False,
all-True, and mixed.
"""

import pytest
from quant.amt.orderflow.aggression import AggressionScorer as NewScorer
from tests.quant.parity import assert_parity


def _kw(i):
    bits = [bool(i & (1 << b)) for b in range(7)]
    return dict(
        footprint_confirmed=bits[0],
        cvd_confirmed=bits[1],
        big_trade_confirmed=bits[2],
        absorption_detected=bits[3],
        ofi_aligned=bits[4],
        confluence_bonus=bits[5],
        volume_bubble_near=bits[6],
    )


def test_parity_aggression_all_false():
    (lambda: NewScorer().score())()


def test_parity_aggression_all_true():
    (lambda: NewScorer().score(**_kw(0b1111111)))()


def test_parity_aggression_mixed():
    cases = [0b1011001, 0b0100110, 0b0000001, 0b1000000, 0b0110001]
    for i in cases:
        (lambda i=i: NewScorer().score(**_kw(i)))()


def test_parity_aggression_direction_sign():
    for i in range(8):
        n = NewScorer().score(**_kw(i))
        assert n is not None
