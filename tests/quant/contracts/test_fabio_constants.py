"""Fabio AMT methodology parameters are named constants, not magic numbers."""
from quant.contracts.constants import (
    FABIO_CVD_THRESHOLD_NSE,
    FABIO_CVD_THRESHOLD_MCX,
    FABIO_OBI_THRESHOLD,
    FABIO_OFI_THRESHOLD,
    FABIO_ABSORPTION_VOL_MULT,
    FABIO_ABSORPTION_RANGE_ATR,
    FABIO_VALUE_AREA_PCT,
)


def test_cvd_thresholds_match_fabio():
    assert FABIO_CVD_THRESHOLD_NSE == 0.5
    assert FABIO_CVD_THRESHOLD_MCX == 0.3


def test_obi_threshold():
    assert FABIO_OBI_THRESHOLD == 0.20


def test_ofi_threshold():
    assert FABIO_OFI_THRESHOLD == 0.10


def test_absorption_parameters_match_fabio():
    """Fabio: Vol > 2x Avg, Range < 0.3 ATR."""
    assert FABIO_ABSORPTION_VOL_MULT == 2.0
    assert FABIO_ABSORPTION_RANGE_ATR == 0.30


def test_value_area_percentage():
    """CME standard: 70% value area."""
    assert FABIO_VALUE_AREA_PCT == 0.70
