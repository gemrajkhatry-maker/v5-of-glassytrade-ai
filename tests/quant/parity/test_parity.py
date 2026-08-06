import pytest

from tests.quant.parity import assert_parity


def _legacy_near():
    return {"x": 1.0}


def _quant_near():
    return {"x": 1.0000001}


def _legacy_far():
    return {"x": 1.0}


def _quant_far():
    return {"x": 2.0}


def test_parity_passes_for_near_equal():
    assert_parity(_legacy_near, _quant_near)


def test_parity_raises_for_mismatch():
    with pytest.raises(AssertionError):
        assert_parity(_legacy_far, _quant_far)


def test_parity_nested_structures():
    leg = {"a": [1, 2.00000001, (3, "x")], "b": {"c": None}, "d": True}
    qnt = {"a": [1, 2.0, (3, "x")], "b": {"c": None}, "d": True}
    assert_parity(lambda: leg, lambda: qnt)


def test_parity_rejects_float_int_type_drift():
    with pytest.raises(AssertionError):
        assert_parity(lambda: 1.0, lambda: 1)


def test_parity_rejects_bool_int_type_drift():
    with pytest.raises(AssertionError):
        assert_parity(lambda: True, lambda: 1)
