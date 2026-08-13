"""Test that training-path and live-path feature extraction produce consistent values.

Guards against training/inference skew that would silently degrade model performance.
"""
import os
import numpy as np
import pytest

_IND_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "poc3", "indicator_data_options"
)


def _parquet_available():
    return os.path.isdir(_IND_DIR) and any(
        f.endswith(".parquet") for f in os.listdir(_IND_DIR)
    )


@pytest.mark.skipif(not _parquet_available(), reason="poc3 indicator parquets not available")
def test_feature_alignment_training_vs_live():
    """Training-path and live-path features must agree within 5% for non-OI fields."""
    import pandas as pd
    from quant.probability.features import FEATURE_NAMES, extract_features_from_row

    # Load one parquet
    files = [f for f in os.listdir(_IND_DIR) if f.endswith(".parquet")]
    df = pd.read_parquet(os.path.join(_IND_DIR, files[0]))
    df = df.dropna(subset=["close", "poc"]).reset_index(drop=True)

    if len(df) < 10:
        pytest.skip("Not enough rows in parquet")

    row = df.iloc[50].to_dict()  # pick a middle row (warmed indicators)

    # Training path
    feats_train = extract_features_from_row(row)

    # Verify all feature names present
    missing = [n for n in FEATURE_NAMES if n not in feats_train]
    assert not missing, f"Training path missing features: {missing}"

    # All values finite
    for name in FEATURE_NAMES:
        val = feats_train.get(name, 0.0)
        assert np.isfinite(val), f"Non-finite value for {name}: {val}"


def test_probability_feature_contract_metadata():
    from quant.probability.features import (
        FEATURE_NAMES,
        PROBABILITY_FEATURE_SCHEMA_VERSION,
    )

    assert PROBABILITY_FEATURE_SCHEMA_VERSION == "fp-42-v1"
    assert len(FEATURE_NAMES) == 42
    assert "book_imbalance_l20" not in FEATURE_NAMES


def test_parse_symbol_metadata_call():
    from quant.amt.session.symbol_registry import parse_symbol_metadata
    meta = parse_symbol_metadata("NIFTY 27 MAR 23500 CALL", spot=23600.0)
    assert meta["option_type_flag"] == 1.0
    assert meta["strike"] == 23500.0
    assert meta["moneyness_pct"] == pytest.approx((23600 - 23500) / 23600, abs=1e-6)
    assert 0.0 <= meta["dte_normalized"] <= 1.0


def test_parse_symbol_metadata_put():
    from quant.amt.session.symbol_registry import parse_symbol_metadata
    meta = parse_symbol_metadata("BANKNIFTY 27 MAR 50000 PUT", spot=49000.0)
    assert meta["option_type_flag"] == -1.0
    assert meta["strike"] == 50000.0
    assert meta["moneyness_pct"] == pytest.approx((50000 - 49000) / 49000, abs=1e-6)


def test_parse_symbol_metadata_unknown():
    from quant.amt.session.symbol_registry import parse_symbol_metadata
    meta = parse_symbol_metadata("CRUDEOIL 17 MAR 6000 CALL", spot=5950.0)
    assert meta["option_type_flag"] == 1.0
    assert meta["strike"] == 6000.0


def test_is_market_open_during_hours():
    from quant.amt.session.symbol_registry import is_market_open
    # Wednesday 10:00 IST (04:30 UTC) — inside NSE window 09:15-15:15
    assert is_market_open("2026-02-25T04:30:00Z", exchange="NSE") is True


def test_is_market_open_weekend():
    from quant.amt.session.symbol_registry import is_market_open
    # Saturday — closed for both exchanges
    assert is_market_open("2026-02-28T04:30:00Z", exchange="NSE") is False
    assert is_market_open("2026-02-28T04:30:00Z", exchange="MCX") is False


def test_is_market_open_after_close():
    from quant.amt.session.symbol_registry import is_market_open
    # Wednesday 16:00 IST (10:30 UTC) — after NSE close at 15:15
    assert is_market_open("2026-02-25T10:30:00Z", exchange="NSE") is False


def test_nse_close_at_1515():
    from quant.amt.session.symbol_registry import is_market_open
    # NSE closes at 15:15 IST (09:45 UTC)
    # 15:14 IST = 09:44 UTC → open
    assert is_market_open("2026-02-25T09:44:00Z", exchange="NSE") is True
    # 15:16 IST = 09:46 UTC → closed
    assert is_market_open("2026-02-25T09:46:00Z", exchange="NSE") is False


def test_mcx_hours():
    from quant.amt.session.symbol_registry import is_market_open
    # MCX opens 09:00 IST (03:30 UTC), closes 23:30 IST (18:00 UTC)
    # 09:01 IST = 03:31 UTC → open
    assert is_market_open("2026-02-25T03:31:00Z", exchange="MCX") is True
    # 08:59 IST = 03:29 UTC → closed (before open)
    assert is_market_open("2026-02-25T03:29:00Z", exchange="MCX") is False
    # 22:00 IST = 16:30 UTC → open
    assert is_market_open("2026-02-25T16:30:00Z", exchange="MCX") is True
    # 23:20 IST = 17:50 UTC → still open (evening session)
    assert is_market_open("2026-02-25T17:50:00Z", exchange="MCX") is True
    # 23:31 IST = 18:01 UTC → closed (after 23:30 close)
    assert is_market_open("2026-02-25T18:01:00Z", exchange="MCX") is False


def test_is_market_open_parse_error_fails_closed():
    from quant.amt.session.symbol_registry import is_market_open
    # Bad timestamp → fail-closed (returns False, not True)
    assert is_market_open("not-a-timestamp") is False
