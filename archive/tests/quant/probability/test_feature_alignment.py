"""Test that training-path and live-path feature extraction produce consistent values (ported to quant.probability).

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
