"""Tests for app.shared.parsing session venue resolution."""

from app.shared.parsing import is_mcx_symbol, resolve_session_market


def test_resolve_mcx_symbol_overrides_nse_exchange():
    assert (
        resolve_session_market("NSE", "CRUDEOIL 14 MAY 8850 CALL") == "MCX"
    )
    assert resolve_session_market("NSE", "NATURALGAS 280 PE") == "MCX"


def test_resolve_nfo_maps_to_nse_calendar():
    assert resolve_session_market("NFO", "NIFTY 27 MAR 23000 CE") == "NSE"


def test_resolve_mcx_exchange_unchanged():
    assert resolve_session_market("MCX", "GOLD 100 CE") == "MCX"


def test_silverm_mini_option_uses_mcx_session():
    sym = "SILVERM 21 APR 260000 PUT"
    assert is_mcx_symbol(sym)
    assert resolve_session_market("NSE", sym) == "MCX"


def test_goldm_mini_option_uses_mcx_session():
    sym = "GOLDM 21 APR 85000 CALL"
    assert is_mcx_symbol(sym)
    assert resolve_session_market("NSE", sym) == "MCX"
