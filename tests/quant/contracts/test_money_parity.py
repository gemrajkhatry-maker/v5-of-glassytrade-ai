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
    import quant.contracts.decimal_utils as du
    import quant.contracts.numeric as nu
    import shared.money as m
    assert du.to_decimal is m.to_decimal
    assert nu.to_float is m.to_float

def test_adapter_converters_match_shared_money():
    import pathlib
    adapter = pathlib.Path("backend/app/infrastructure/adapters/dhan_broker_adapter.py").read_text()
    assert "shared.money" in adapter
    assert "Decimal(str(value))" not in adapter
    feed = pathlib.Path("backend/app/infrastructure/adapters/dhan_order_feed.py").read_text()
    assert "def _to_float" not in feed

def test_adapter_lenient_wrapper_preserves_old_semantics():
    from app.infrastructure.adapters.dhan_broker_adapter import _to_decimal
    assert _to_decimal("abc") == Decimal("0")
    assert _to_decimal(None) == Decimal("0")
    assert _to_decimal(None, default="0.01") == Decimal("0.01")
    assert _to_decimal("1.5") == Decimal("1.5")
    assert _to_decimal([]) == Decimal("0")


def test_registry_is_sole_lot_source():
    from quant.contracts.instrument_registry import (
        DEFAULT_REGISTRY,
    )
    from quant.contracts.instrument_registry import (
        get_lot_size as reg_lot,
    )
    from quant.contracts.instrument_registry import (
        get_tick_size as reg_tick,
    )
    assert DEFAULT_REGISTRY.try_resolve("NIFTY").lot_size == 65
    assert DEFAULT_REGISTRY.try_resolve("BANKNIFTY").lot_size == 30
    assert DEFAULT_REGISTRY.try_resolve("CRUDEOILM").lot_size == 10
    assert reg_lot("NIFTY") == 65
    assert reg_tick("CRUDEOIL") == 1.0
    # Parity: every registry-covered root agrees with market_info + dhan constants
    from brokers.broker.dhan.domain.constants import LOT_SIZES as DHAN_LOTS
    from brokers.broker.market_info import get_lot_size
    for spec in DEFAULT_REGISTRY.specs():
        assert get_lot_size(spec.root) == spec.lot_size, spec.root
        if spec.root in DHAN_LOTS:
            assert DHAN_LOTS[spec.root] == spec.lot_size, spec.root
    # Non-registry extras still work (stocks, aliases) — behavior preserved
    assert get_lot_size("RELIANCE") == 250
    assert get_lot_size("NIFTY 50") == 65
    assert get_lot_size("UNKNOWN_XYZ") == 1


def test_backoff_golden_table():
    from shared.net_policy import capped_exp_delay
    assert capped_exp_delay(0) == 0.5
    assert capped_exp_delay(1) == 1.0
    assert capped_exp_delay(2) == 2.0
    assert capped_exp_delay(10) == 30.0


def test_net_policy_values_match_dhan_constants():
    import shared.net_policy as np
    from brokers.broker.dhan.domain import constants as dc
    assert dc.DEFAULT_TIMEOUT_SECONDS == np.DEFAULT_TIMEOUT_SECONDS == 10.0
    assert dc.DEFAULT_MAX_RETRIES == np.DEFAULT_MAX_RETRIES == 3
    assert dc.DEFAULT_RETRY_BACKOFF_FACTOR == np.DEFAULT_RETRY_BACKOFF_FACTOR == 0.5
    assert dc.WS_RECONNECT_DELAY_SECONDS == np.WS_RECONNECT_DELAY_SECONDS == 5.0
    assert dc.WS_MAX_RECONNECT_ATTEMPTS == np.WS_MAX_RECONNECT_ATTEMPTS == 30
    assert dc.INSTRUMENT_CACHE_TTL_SECONDS == np.INSTRUMENT_CACHE_TTL_SECONDS == 86400
