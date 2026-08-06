"""Parity: market_state_engine moved module vs legacy shim."""

from quant.amt.market.state_engine import (
    classify_zone as new_classify_zone,
    detect_market_state as new_detect_market_state,
)
from app.domain.fabio_ai.services.market_state_engine import (
    classify_zone as legacy_classify_zone,
    detect_market_state as legacy_detect_market_state,
)
from tests.quant.parity import assert_parity

# ---------------------------------------------------------------------------
# detect_market_state — BALANCED / IMBALANCED + zones
# ---------------------------------------------------------------------------


def _cases():
    return [
        # inside VA, balanced -> BALANCED / NEAR_POC
        dict(price=100.05, poc=100.0, vah=105.0, val=95.0, tick_size=0.10,
             has_displacement=False, has_acceptance=True, balance_ratio=0.5),
        # inside VA, balanced, price near upper half -> NEAR_VAH
        dict(price=103.0, poc=100.0, vah=105.0, val=95.0, tick_size=0.10,
             has_displacement=False, has_acceptance=True, balance_ratio=0.5),
        # inside VA, balanced, price near lower half -> NEAR_VAL
        dict(price=97.0, poc=100.0, vah=105.0, val=95.0, tick_size=0.10,
             has_displacement=False, has_acceptance=True, balance_ratio=0.5),
        # at VAH boundary, balanced
        dict(price=105.0, poc=100.0, vah=105.0, val=95.0, tick_size=0.10,
             has_displacement=False, has_acceptance=False, balance_ratio=0.50),
        # at VAL boundary, balanced
        dict(price=95.0, poc=100.0, vah=105.0, val=95.0, tick_size=0.10,
             has_displacement=False, has_acceptance=False, balance_ratio=0.50),
        # low balance ratio -> IMBALANCED
        dict(price=100.0, poc=100.0, vah=105.0, val=95.0, tick_size=0.10,
             has_displacement=False, has_acceptance=False, balance_ratio=0.3),
        # outside VA + displacement + acceptance -> IMBALANCED / OUTSIDE_VA
        dict(price=106.0, poc=100.0, vah=105.0, val=95.0, tick_size=0.10,
             has_displacement=True, has_acceptance=True),
        # outside VA, no displacement -> IMBALANCED / OUTSIDE_VA
        dict(price=106.0, poc=100.0, vah=105.0, val=95.0, tick_size=0.10,
             has_displacement=False, has_acceptance=False),
        # below VAL -> IMBALANCED
        dict(price=93.0, poc=100.0, vah=105.0, val=95.0, tick_size=0.10,
             has_displacement=False, has_acceptance=False),
        # active leg VA overrides session VA
        dict(price=108.0, poc=100.0, vah=105.0, val=95.0, tick_size=0.10,
             has_displacement=True, has_acceptance=True, balance_ratio=0.8,
             leg_poc=107.0, leg_vah=110.0, leg_val=104.0),
        # extreme vwap deviation flag propagates
        dict(price=106.0, poc=100.0, vah=105.0, val=95.0, tick_size=0.10,
             has_displacement=True, has_acceptance=True,
             vwap_deviation_sigmas=3.5),
        # ib break flags ignored for state but pass through cleanly
        dict(price=100.0, poc=100.0, vah=105.0, val=95.0, tick_size=0.10,
             has_displacement=False, has_acceptance=True, balance_ratio=0.5,
             ib_break_direction="UP", ib_complete=True, ib_high=102.0, ib_low=98.0),
    ]


def test_parity_detect_market_state():
    for kwargs in _cases():
        assert_parity(legacy_detect_market_state, new_detect_market_state, **kwargs)


def test_parity_detect_market_state_defaults():
    assert_parity(
        legacy_detect_market_state,
        new_detect_market_state,
        price=100.0,
        poc=100.0,
        vah=105.0,
        val=95.0,
        tick_size=0.10,
        has_displacement=False,
        has_acceptance=True,
    )


# ---------------------------------------------------------------------------
# classify_zone — above / below / inside
# ---------------------------------------------------------------------------


def test_parity_classify_zone():
    cases = [
        (103.0, 100.0, 105.0, 95.0),  # near VAH
        (97.0, 100.0, 105.0, 95.0),   # near VAL
        (100.5, 100.0, 105.0, 95.0),  # near POC
        (100.8, 100.0, 105.0, 95.0),  # near POC upper bound
        (104.0, 100.0, 105.0, 95.0),  # upper half, far from POC
        (96.0, 100.0, 105.0, 95.0),   # lower half, far from POC
        (105.0, 100.0, 105.0, 95.0),  # exactly at VAH
        (95.0, 100.0, 105.0, 95.0),   # exactly at VAL
        (100.0, 100.0, 105.0, 95.0),  # exactly at POC
    ]
    for price, poc, vah, val in cases:
        assert_parity(legacy_classify_zone, new_classify_zone, price, poc, vah, val)
