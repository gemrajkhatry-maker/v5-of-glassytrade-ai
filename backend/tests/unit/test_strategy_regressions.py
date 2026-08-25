"""Strategy regression tests — lot-size invariants and anchored option-type
detection (correctness classes flagged in the production review).

Lot sizes must agree across the broker static tables, the Dhan domain
constants, and the authoritative ``quant/contracts/exchange_config``
(NSE 65/30/60, MCX GOLDM 100). Option-type detection must be anchored
(trailing CALL/PUT word or digit-suffixed CE/PE) so substring matches in
underlying names can never mislabel a contract.
"""
from __future__ import annotations

from quant.amt.analyzer import AMTAnalyzer
from quant.amt.session.selector import MCX_LOT_SIZES
from quant.contracts.exchange_config import ExchangeConfig


# ---------------------------------------------------------------------------
# Lot-size invariants
# ---------------------------------------------------------------------------

def test_nse_lot_sizes_agree_across_all_sources():
    """market_info get_lot_size, dhan constants and exchange_config must all
    carry the exchange-authoritative Aug 2026 NSE lots (65/30/60)."""
    from brokers.broker.market_info import get_lot_size
    from brokers.broker.dhan.domain.constants import LOT_SIZES as DHAN_LOTS
    from quant.contracts.instrument_registry import DEFAULT_REGISTRY

    cfg = ExchangeConfig.for_exchange("NSE")
    expected = {"NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 60}
    for sym, lot in expected.items():
        assert get_lot_size(sym) == lot, f"market_info {sym} lot is {get_lot_size(sym)}"
        assert DHAN_LOTS[sym] == lot, f"dhan constants {sym} lot is {DHAN_LOTS[sym]}"
        assert cfg.get_lot_size(sym) == lot
        assert DEFAULT_REGISTRY.resolve(sym).lot_size == lot
    assert get_lot_size("NIFTY 50") == 65
    assert get_lot_size("NIFTY BANK") == 30
    assert get_lot_size("NIFTY FIN SERVICE") == 60
    assert get_lot_size("MIDCPNIFTY") == DHAN_LOTS["MIDCPNIFTY"] == 120
    assert get_lot_size("SENSEX") == DHAN_LOTS["SENSEX"] == 20
    assert get_lot_size("BANKEX") == DHAN_LOTS["BANKEX"] == 30


def test_crudeoil_mini_lot_agrees():
    """CRUDEOILM (mini crude, 10 bbl) must agree across sources."""
    from brokers.broker.market_info import get_lot_size

    assert get_lot_size("CRUDEOILM") == 10
    assert MCX_LOT_SIZES["CRUDEOILM"] == 10


def test_goldm_lot_size_is_100_everywhere():
    """GOLDM (live-traded mini gold) was 10 in two static tables vs 100 in the
    authoritative config — a 10x risk-sizing error. All sources must agree."""
    from brokers.broker.market_info import get_lot_size

    assert get_lot_size("GOLDM") == 100
    assert MCX_LOT_SIZES["GOLDM"] == 100
    cfg = ExchangeConfig.for_exchange("MCX")
    assert cfg.get_lot_size("GOLDM") == 100


# ---------------------------------------------------------------------------
# Anchored option-type detection
# ---------------------------------------------------------------------------

def test_detect_option_type_anchored():
    """CE/PE/CALL/PUT must only match as a trailing token, never as a
    substring of the underlying name."""
    detect = AMTAnalyzer._detect_option_type

    # Normal NSE/MCX option symbols.
    assert detect("NIFTY 11 AUG 24600 CALL") == "CALL"
    assert detect("NIFTY 11 AUG 24600 PUT") == "PUT"
    assert detect("CRUDEOIL 17 AUG 7450 CALL") == "CALL"
    # Paper-broker style compact symbols.
    assert detect("NIFTY11AUG2624600CE") == "CALL"
    assert detect("NIFTY11AUG2624600PE") == "PUT"
    # Adversarial underlying names containing CE/PE/CALL/PUT as substrings.
    assert detect("PRINCE 25 JUN 100 PUT") == "PUT"
    assert detect("SPICEMOTORS 25 JUN 120 CALL") == "CALL"
    assert detect("CALLAWAY 25 JUN 500 PUT") == "PUT"
    assert detect("PENCESTOCKS 25 JUN 90 PE") == "PUT"
    assert detect("NIFTY 11 AUG 24600 FUT") == "UNKNOWN"
    assert detect("") == "UNKNOWN"


def test_dhan_adapter_instrument_detection_anchored():
    """The Dhan adapter must not misroute/mislabel option symbols whose
    underlying contains CE/PE/CALL/PUT as a substring."""
    from backend.app.infrastructure.adapters.dhan_adapter import (
        DhanMarketDataAdapter,
    )
    from brokers.broker.entities import OptionType

    adapter = DhanMarketDataAdapter(
        symbols=["NIFTY"], client_id="test", access_token="token"
    )
    inst = adapter._make_instrument("PRINCE 25 JUN 100 PUT")
    assert inst.option_type == OptionType.PUT, inst.option_type

    inst2 = adapter._make_instrument("NIFTY 11 AUG 24600 CALL")
    assert inst2.option_type == OptionType.CALL, inst2.option_type

    inst3 = adapter._make_instrument("SPICEMOTORS 25 JUN 120 CE")
    assert inst3.option_type == OptionType.CALL, inst3.option_type

    fut = adapter._make_instrument("NIFTY AUG FUT")
    assert fut.option_type is None
