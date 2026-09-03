# tests/quant/contracts/test_money_parity.py
from decimal import Decimal
from shared.money import to_decimal, to_float

def test_none_maps_to_zero():
    assert to_decimal(None) == Decimal("0")
    assert to_float(None) == 0.0

def test_bad_string_raises_for_decimal_returns_default_for_float():
    import pytest
    with pytest.raises(ValueError):
        to_decimal("abc")
    assert to_float("abc") == 0.0
    assert to_float("abc", default=1.5) == 1.5

def test_decimal_passthrough_and_float_string():
    assert to_decimal(Decimal("1.5")) == Decimal("1.5")
    assert to_decimal(123.45) == Decimal("123.45")
    assert to_float(Decimal("123.45")) == 123.45

def test_quant_shims_are_shared_money():
    import shared.money as m
    import quant.contracts.decimal_utils as du
    import quant.contracts.numeric as nu
    assert du.to_decimal is m.to_decimal
    assert nu.to_float is m.to_float
