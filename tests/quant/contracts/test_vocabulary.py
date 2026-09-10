"""D-20/21/22: one owner for the repeated domain vocabulary."""

from quant.contracts.vocabulary import (
    absorption_direction,
    is_call_symbol,
    is_closing_phase,
    is_opening_phase,
    is_put_symbol,
)


def test_absorption_direction_canonical_semantics():
    assert absorption_direction("SELL_ABSORBED") == "LONG"
    assert absorption_direction("BUY_ABSORBED") == "SHORT"
    # Legacy bare forms keep working (the DTO now sends _ABSORBED).
    assert absorption_direction("SELL") == "LONG"
    assert absorption_direction("BUY") == "SHORT"
    assert absorption_direction("") is None


def test_option_kind_is_gated_on_being_an_option():
    assert is_call_symbol("NIFTY 24600 CALL")
    assert is_call_symbol("NIFTY24600CE")
    assert not is_call_symbol("CRUDEOILM 17 AUG FUT")
    assert is_put_symbol("NIFTY 24600 PUT")
    assert is_put_symbol("NIFTY24600PE")
    # A futures root that merely ends in CE must not classify as a call.
    assert not is_call_symbol("SOMECE")


def test_session_phase_classification_is_single_valued():
    assert is_opening_phase("NSE_OPENING")
    assert is_opening_phase("PRE_MARKET")
    assert not is_opening_phase("NSE_PRIMARY")
    assert is_closing_phase("NSE_CLOSE")
    assert is_closing_phase("POST_MARKET")
    assert not is_closing_phase("NSE_PRIMARY")
    # PRE_MARKET is opening noise, NOT a close — the two sets must not overlap.
    assert not is_closing_phase("PRE_MARKET")
