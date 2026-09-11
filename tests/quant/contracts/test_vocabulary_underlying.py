from quant.contracts.vocabulary import extract_underlying


def test_extract_underlying_common_option_formats():
    assert extract_underlying("NIFTY-25SEP26-25000-CE") == "NIFTY-25SEP26"
    assert extract_underlying("BANKNIFTY25SEP2625000PE") == "BANKNIFTY25SEP"


def test_extract_underlying_is_safe_for_empty_and_roots():
    assert extract_underlying("") == ""
    assert extract_underlying("NIFTY") == "NIFTY"
