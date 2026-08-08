from decimal import Decimal

from quant.contracts.numeric import to_float


def test_to_float_coerces_ints_floats_and_strings():
    assert to_float(1) == 1.0
    assert to_float(2.5) == 2.5
    assert to_float("3.75") == 3.75
    assert to_float(Decimal("4.5")) == 4.5


def test_to_float_returns_default_on_none_and_bad_values():
    assert to_float(None) == 0.0
    assert to_float("abc") == 0.0
    assert to_float(object()) == 0.0


def test_to_float_honors_custom_default():
    assert to_float(None, default=None) is None
    assert to_float("n/a", default=None) is None
