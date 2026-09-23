# tests/quant/test_underlying_required.py
"""Tests for Underlying Feed Contract in Option Analysis (Task 9)."""

from quant.amt.session.futures_provider import extract_option_date


def test_futures_provider_extracts_underlying_symbol():
    res = extract_option_date("NIFTY 28 AUG 24500 CE")
    assert res is not None
    underlying, day, month = res
    assert underlying == "NIFTY"
    assert day == "28"
    assert month == "AUG"


def test_mcx_futures_provider_extracts_commodity_underlying():
    res = extract_option_date("SILVERM 28 AUG 235000 CALL")
    assert res is not None
    underlying, day, month = res
    assert underlying == "SILVERM"
    assert day == "28"
    assert month == "AUG"
