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

def test_adapter_converters_match_shared_money():
    import pathlib
    adapter = pathlib.Path("backend/app/infrastructure/adapters/dhan_broker_adapter.py").read_text()
    assert "def _to_decimal" not in adapter
    feed = pathlib.Path("backend/app/infrastructure/adapters/dhan_order_feed.py").read_text()
    assert "def _to_float" not in feed

def test_registry_is_sole_lot_source():
    from quant.contracts.instrument_registry import (
        DEFAULT_REGISTRY, get_lot_size as reg_lot, get_tick_size as reg_tick,
    )
    assert DEFAULT_REGISTRY.try_resolve("NIFTY").lot_size == 65
    assert DEFAULT_REGISTRY.try_resolve("BANKNIFTY").lot_size == 30
    assert DEFAULT_REGISTRY.try_resolve("CRUDEOILM").lot_size == 10
    assert reg_lot("NIFTY") == 65
    assert reg_tick("CRUDEOIL") == 1.0
    # Parity: every registry-covered root agrees with market_info + dhan constants
    from brokers.broker.market_info import get_lot_size
    from brokers.broker.dhan.domain.constants import LOT_SIZES as DHAN_LOTS
    for spec in DEFAULT_REGISTRY.specs():
        assert get_lot_size(spec.root) == spec.lot_size, spec.root
        if spec.root in DHAN_LOTS:
            assert DHAN_LOTS[spec.root] == spec.lot_size, spec.root
    # Non-registry extras still work (stocks, aliases) — behavior preserved
    assert get_lot_size("RELIANCE") == 250
    assert get_lot_size("NIFTY 50") == 65
    assert get_lot_size("UNKNOWN_XYZ") == 1
