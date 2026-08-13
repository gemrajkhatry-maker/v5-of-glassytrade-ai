"""Regression tests: lot-size configuration must match exchange authority.

The NSE series (Aug 2026) lot sizes are NIFTY=65, BANKNIFTY=30, FINNIFTY=60.
The config previously said 25/15/25 (NIFTY positions 2.6x understated) and the
loader silently defaulted missing lot_size to 25.
"""

import os

import pytest

from app.config_models.loader import load_config, _parse_symbol
from quant.contracts.exchange_config import ExchangeConfig


def _load():
    old_env = dict(os.environ)
    try:
        os.environ["GLASSYTRADE_ENV"] = "paper"
        os.environ["GLASSYTRADE_STRATEGY"] = "nse_options"
        return load_config(strategy="nse_options")
    finally:
        os.environ.clear()
        os.environ.update(old_env)


def test_config_lot_sizes_match_exchange_series():
    cfg = _load()
    nse = cfg.exchanges["NSE"].symbols
    assert nse["NIFTY"].lot_size == 65
    assert nse["BANKNIFTY"].lot_size == 30
    assert nse["FINNIFTY"].lot_size == 60


def test_parse_symbol_requires_lot_size():
    """A symbol without lot_size must fail fast, not silently default to 25."""
    with pytest.raises(ValueError, match="lot_size"):
        _parse_symbol("NIFTY", {"enabled": True})


def test_exchange_config_raises_for_unknown_lot_size():
    """get_lot_size must raise for an unknown underlying, not return 25."""
    cfg = ExchangeConfig._nse_defaults()
    assert cfg.get_lot_size("NIFTY") == 65
    with pytest.raises(KeyError):
        cfg.get_lot_size("UNKNOWN_INDEX")
