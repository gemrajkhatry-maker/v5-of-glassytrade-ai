"""Regression tests for the lot-size chain (P0).

The old ``resolve_symbol`` rebuilt a minimal DhanInstrument without lot_size,
so ``get_lot_size()`` returned 1 for every option contract (silent fallback).
Combined with config lot sizes of NIFTY=25/BANKNIFTY=15 (vs exchange 65/30/60)
this understated NIFTY position sizing 2.6x.

These tests pin the corrected behavior: full instruments carry the exchange
lot size and failures are explicit, never a silent ``1``.
"""

import pytest

from brokers.broker.dhan.application.broker import DhanBroker, DhanExchangeConfig
from brokers.broker.dhan.application.config import DhanConfig
from brokers.broker.dhan.domain import DhanInstrument
from brokers.broker.dhan.domain import InstrumentTypeEnum, OptionType
from brokers.broker.dhan.domain.value_objects import ExchangeSegment
from brokers.broker.dhan.domain.errors import DhanSymbolNotFoundError


class _StubMapper:
    """ISymbolMapper stub backed by a tiny instrument master."""

    def __init__(self, instruments: list[DhanInstrument]) -> None:
        self._instruments = {i.security_id: i for i in instruments}
        self.is_cache_stale = False

    @property
    def instruments(self):
        return self._instruments

    async def get_security_id(self, symbol, exchange_segment):
        for inst in self._instruments.values():
            if (
                inst.trading_symbol.upper() == symbol.upper()
                and inst.exchange_segment == exchange_segment
            ):
                return inst.security_id
        return None

    async def get_instrument(self, security_id):
        return self._instruments.get(security_id)


def _nifty_option() -> DhanInstrument:
    return DhanInstrument(
        security_id="101",
        trading_symbol="NIFTY 11 AUG 24600 CALL",
        symbol="NIFTY",
        exchange_segment=ExchangeSegment.NSE_FNO,
        instrument_type=InstrumentTypeEnum.INDEX_OPTION,
        expiry_date=None,
        strike=24600.0,
        option_type=OptionType.CALL,
        lot_size=65,
        tick_size=0.05,
    )


def _nifty_index() -> DhanInstrument:
    return DhanInstrument(
        security_id="102",
        trading_symbol="NIFTY",
        symbol="NIFTY",
        exchange_segment=ExchangeSegment.IDX_I,
        instrument_type=InstrumentTypeEnum.INDEX,
        expiry_date=None,
        strike=None,
        option_type=None,
        lot_size=1,  # indices carry lot_size=1 in the master
        tick_size=0.05,
    )


def _broker(instruments) -> DhanBroker:
    return DhanBroker(
        config=DhanConfig(client_id="C", access_token="T"),
        symbol_mapper=_StubMapper(instruments),
    )


def test_resolve_symbol_returns_full_instrument_with_lot_size():
    """resolve_symbol must carry the exchange lot size, not a minimal stub."""
    broker = _broker([_nifty_option()])
    inst = broker._run_async(
        broker.resolve_symbol("NIFTY 11 AUG 24600 CALL")
    )
    assert inst.lot_size == 65
    assert inst.strike == 24600.0
    assert inst.option_type == OptionType.CALL


def test_get_lot_size_returns_exchange_lot_size():
    broker = _broker([_nifty_option()])
    assert broker.get_lot_size("NIFTY 11 AUG 24600 CALL") == 65


def test_get_lot_size_raises_instead_of_silent_one():
    """Unresolvable symbol must raise — the old silent `return 1` is gone."""
    broker = _broker([_nifty_option()])
    with pytest.raises(DhanSymbolNotFoundError):
        broker.get_lot_size("BOGUS 99 DEC 1 CALL")


def test_exchange_config_resolves_underlying_root_via_option():
    """DhanExchangeConfig.get_lot_size('NIFTY') must use an option contract's
    lot size (65), NOT the index's lot_size=1."""
    broker = _broker([_nifty_option(), _nifty_index()])
    cfg = DhanExchangeConfig(broker)
    assert cfg.get_lot_size("NIFTY") == 65
    assert cfg.get_lot_size("NIFTY 11 AUG 24600 CALL") == 65


def test_exchange_config_raises_for_unknown_underlying():
    # NOTE: "GOLDM" was originally used here as an "unknown" underlying.
    # Since ae0d832 the step-3 fallback resolves GOLDM via quant
    # ExchangeConfig (MCX lot=100), so it no longer raises. The raise path
    # is pinned with a genuinely unknown underlying instead.
    broker = _broker([_nifty_option()])
    cfg = DhanExchangeConfig(broker)
    with pytest.raises(DhanSymbolNotFoundError):
        cfg.get_lot_size("ZZNOTREAL")
