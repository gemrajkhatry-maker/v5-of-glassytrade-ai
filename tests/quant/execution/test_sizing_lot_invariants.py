"""Sizing lot invariants (paper-protocol + expiry-halving regression).

Two production defects shared one root cause: ``SessionRisk.position_size``
could return quantities that are NOT multiples of ``lot_size``.

1. **Aggressive-mode path** (``base_risk_pct >= 0.05``): the day-of-week
   multiplier was applied *after* ``lots * lot_size`` with no re-snap, so on
   Mon/Fri (multiplier 0.5) a 333-lot 16,650-unit position became 8,325 — a
   half-lot quantity that can never be ordered on-exchange.
2. **House-Money path** was already correct (final ``int(qty // lot_size) *
   lot_size`` re-snap at the end), proving the intended contract.

The on-exchange orderability invariant is: every returned quantity is an
exact lot multiple (or 0). The expiry-halving and day-of-week scaling must
not break it — re-snap after scaling, rounding DOWN (never up-size risk).

Also pins the expiry afternoon protocol itself: half the normal position,
still a lot multiple.
"""

import pytest

from quant.execution.risk import SessionRisk


# Monday (0) and Friday (4) carry the 0.5 multiplier in
# quant.execution.risk.DAY_OF_WEEK_MULTIPLIER; mid-week is 1.0.
_HALF_DAYS = [0, 4]
_FULL_DAYS = [1, 2, 3]


@pytest.mark.parametrize("day", _FULL_DAYS + _HALF_DAYS)
def test_position_size_is_always_a_lot_multiple(day):
    risk = SessionRisk(starting_equity=1_000_000.0, day_of_week=day)
    qty = risk.position_size(entry=100.0, sl=90.0, lot_size=50)
    assert qty % 50 == 0, (
        f"day={day}: position_size returned {qty}, not a multiple of lot 50 — "
        "un-orderable quantity on-exchange"
    )


@pytest.mark.parametrize("day", _FULL_DAYS + _HALF_DAYS)
def test_expiry_size_is_always_a_lot_multiple(day):
    risk = SessionRisk(starting_equity=1_000_000.0, day_of_week=day)
    qty = risk.position_size(entry=100.0, sl=90.0, lot_size=50, is_expiry=True)
    assert qty % 50 == 0, (
        f"day={day}: expiry position_size returned {qty}, not a multiple of "
        "lot 50 — un-orderable quantity on-exchange"
    )


@pytest.mark.parametrize("day", _FULL_DAYS)
def test_expiry_afternoon_protocol_halves_and_stays_orderable(day):
    risk = SessionRisk(starting_equity=1_000_000.0, day_of_week=day)
    normal = risk.position_size(entry=100.0, sl=90.0, lot_size=50)
    expiry = risk.position_size(entry=100.0, sl=90.0, lot_size=50, is_expiry=True)
    assert expiry <= normal // 2, (
        "expiry day must size at most half the normal position"
    )
    assert expiry % 50 == 0


@pytest.mark.parametrize("day", _FULL_DAYS + _HALF_DAYS)
def test_day_of_week_scaling_rounds_down_to_lots(day):
    """The multiplier may reduce the position but never produce a half-lot."""
    risk = SessionRisk(starting_equity=1_000_000.0, day_of_week=day)
    base_risk = SessionRisk(starting_equity=1_000_000.0, day_of_week=1)
    qty = risk.position_size(entry=100.0, sl=90.0, lot_size=50)
    full = base_risk.position_size(entry=100.0, sl=90.0, lot_size=50)
    assert qty <= full, f"day={day}: scaled size {qty} exceeds full-day {full}"
    assert qty % 50 == 0


def test_pyramid_size_is_always_a_lot_multiple():
    """Same invariant through the pyramid path (it floors lots already, but
    pin it so a future refactor of position_size cannot leak half-lots)."""
    risk = SessionRisk(starting_equity=1_000_000.0, day_of_week=1)
    # Force tier to CUSHION_TIER_2 semantics via session R: simplest is to
    # check whatever it returns is lot-aligned, including the 0 early-return.
    qty = risk.pyramid_position_size(entry=100.0, sl=90.0, lot_size=50)
    assert qty == 0 or qty % 50 == 0


def test_half_day_size_does_not_exceed_full_day():
    risk_full = SessionRisk(starting_equity=1_000_000.0, day_of_week=2)
    risk_half = SessionRisk(starting_equity=1_000_000.0, day_of_week=0)
    full = risk_full.position_size(entry=100.0, sl=90.0, lot_size=50)
    half = risk_half.position_size(entry=100.0, sl=90.0, lot_size=50)
    assert half <= full
