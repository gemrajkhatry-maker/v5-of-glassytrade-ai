"""Fabio AMT methodology parameters are named constants, not magic numbers."""
from quant.contracts.constants import (
    FABIO_CVD_THRESHOLD_NSE,
    FABIO_CVD_THRESHOLD_MCX,
    FABIO_OBI_THRESHOLD,
    FABIO_OFI_THRESHOLD,
    FABIO_ABSORPTION_VOL_MULT,
    FABIO_ABSORPTION_RANGE_ATR,
    ABSORPTION_VOL_MULT,
    ABSORPTION_RANGE_RATIO_MAX,
    VALUE_AREA_PCT,
)


def test_cvd_thresholds_match_fabio():
    assert FABIO_CVD_THRESHOLD_NSE == 0.5
    assert FABIO_CVD_THRESHOLD_MCX == 0.3


def test_obi_threshold():
    assert FABIO_OBI_THRESHOLD == 0.20


def test_ofi_threshold():
    assert FABIO_OFI_THRESHOLD == 0.10


def test_absorption_parameters_match_fabio():
    """Fabio AMT spec §7.2: V_b >= 1.50 x V_bar_20 and (H_b - L_b) <= 0.50 x H_range.

    The old values were 2.0x volume and 0.30 x ATR, neither of which the spec
    contains. The review's C7 finding fixed three things at once:
      * the volume multiple (2.0 -> 1.50);
      * the range threshold (0.30 -> 0.50);
      * the range DENOMINATOR — ATR(14) replaced by H_range, the 20-bar average
        RANGE (ATR also counts overnight gaps, so it is a different statistic,
        not just a different number).
    Both tests are load-bearing: `absorption_detected` drives the Triple-A
    WAITING->ABSORBING transition and the pyramid authorisation floor."""
    assert FABIO_ABSORPTION_VOL_MULT == 1.50
    assert FABIO_ABSORPTION_RANGE_ATR == 0.50
    # The FABIO_* aliases must never drift from the canonical constants.
    assert FABIO_ABSORPTION_VOL_MULT == ABSORPTION_VOL_MULT
    assert FABIO_ABSORPTION_RANGE_ATR == ABSORPTION_RANGE_RATIO_MAX


def test_value_area_percentage():
    """Fabio AMT spec §5.1 rule 3: the value area is 68.2% of total volume.

    The old constant was 0.70, and this test asserted 0.70 as correct, which
    certified the drift the review flagged (C5). A wider VA is the boundary
    that classifies the whole market, so this number is load-bearing."""
    assert VALUE_AREA_PCT == 0.682
