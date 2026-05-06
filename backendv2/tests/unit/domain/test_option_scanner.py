"""Unit tests for backendv2 option scanner."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from unittest.mock import MagicMock

from app.domain.fabio_ai.services.option_scanner import (
    ContractSwitchGuard,
    OptionScannerService,
    ScanResult,
)


@dataclass
class _OptionContract:
    symbol: str
    ltp: float
    oi: int
    volume: int
    bid: float
    ask: float
    delta: float = 0.5
    iv: float = 10.0


@dataclass
class _OptionChain:
    atm_strike: float
    calls: dict
    puts: dict
    expiry: datetime
    strikes: list[float]


def _make_option(
    strike: int,
    underlying: str,
    option_type: str,
    ltp: float = 120.0,
    oi: int = 100000,
    volume: int = 10_000,
    bid: float = 119.8,
    ask: float = 120.2,
) -> _OptionContract:
    return _OptionContract(
        symbol=f"{underlying} 20 MAR {strike} {option_type}",
        ltp=ltp,
        oi=oi,
        volume=volume,
        bid=bid,
        ask=ask,
    )


def _chain(underlying: str, atm: float, strike_step: int = 50):
    strikes = [atm + i * strike_step for i in range(-2, 3)]
    calls = {float(s): _make_option(int(s), underlying, "CE") for s in strikes}
    puts = {float(s): _make_option(int(s), underlying, "PE") for s in strikes}
    return _OptionChain(
        atm_strike=atm,
        calls=calls,
        puts=puts,
        expiry=datetime.now(tz=timezone.utc) + timedelta(days=7),
        strikes=strikes,
    )


def _scan_with_mock(chain_lookup):
    class _Broker:
        def get_option_chain(self, underlying, exchange="NFO", expiry_index=0):
            return chain_lookup(underlying=underlying, exchange=exchange, expiry_index=expiry_index)

    return OptionScannerService(_Broker())


def test_scan_result_shape():
    scanner = _scan_with_mock(lambda **_: _chain("NIFTY", 23400))
    out = scanner.scan_top_n(n=3, underlyings=["NIFTY"], top_per_underlying=3)
    assert out
    first = out[0]
    assert isinstance(first, ScanResult)
    assert first.symbol
    assert first.underlying == "NIFTY"
    assert first.expiry
    assert first.score >= 0


def test_scan_filters_spread():
    chain = _chain("NIFTY", 23400)
    chain.calls[23400.0] = _make_option(23400, "NIFTY", "CE", bid=100.0, ask=200.0, ltp=120.0, oi=100000)
    chain.puts[23400.0] = _make_option(23400, "NIFTY", "PE", bid=100.0, ask=200.0, ltp=120.0, oi=100000)
    scanner = _scan_with_mock(lambda **_: chain)
    assert scanner.scan_top_n(n=2, underlyings=["NIFTY"]) == []


def test_scan_filters_low_oi():
    chain = _chain("NIFTY", 23400)
    chain.calls[23400.0] = _make_option(23400, "NIFTY", "CE", oi=100, ltp=120.0)
    chain.puts[23400.0] = _make_option(23400, "NIFTY", "PE", oi=100, ltp=120.0)
    scanner = _scan_with_mock(lambda **_: chain)
    assert scanner.scan_top_n(n=2, underlyings=["NIFTY"]) == []


def test_scan_round_robin_across_underlyings():
    chain_nifty = _chain("NIFTY", 23400)
    chain_bank = _chain("BANKNIFTY", 51400, strike_step=100)
    def lookup(*, underlying, **_):
        return {"NIFTY": chain_nifty, "BANKNIFTY": chain_bank}.get(underlying)
    scanner = _scan_with_mock(lookup)
    out = scanner.scan_top_n(n=4, underlyings=["NIFTY", "BANKNIFTY"], top_per_underlying=2)
    assert [r.underlying for r in out[:4]] in (["NIFTY", "BANKNIFTY", "NIFTY", "BANKNIFTY"], ["BANKNIFTY", "NIFTY", "BANKNIFTY", "NIFTY"])


def test_fallback_atm_contract_used_when_no_nearby_candidates():
    chain = _chain("NIFTY", 23400)
    chain.calls = {23400.0: _make_option(23400, "NIFTY", "CE")}
    chain.puts = {}
    scanner = _scan_with_mock(lambda **_: chain)
    out = scanner.scan_top_n(n=1, underlyings=["NIFTY"])
    assert len(out) == 1
    assert out[0].strike == 23400


def test_preferred_option_type_bank_and_nifty():
    scanner = _scan_with_mock(lambda **_: _chain("BANKNIFTY", 51400, strike_step=100))
    out = scanner.scan_top_n(n=2, preferred_option_type="PE", exchange="NFO")
    assert out
    assert all(item.underlying == "BANKNIFTY" for item in out)


def test_scanner_handles_none_chain():
    scanner = OptionScannerService(MagicMock())
    scanner._broker.get_option_chain.return_value = None
    assert scanner.scan_top_n(n=3, underlyings=["NIFTY"]) == []


def test_scanner_passes_exchange_to_broker():
    broker = MagicMock()
    scanner = OptionScannerService(broker)
    broker.get_option_chain.return_value = _chain("CRUDEOIL", 7800, strike_step=100)
    scanner.scan_top_n(n=1, underlyings=["CRUDEOIL"], exchange="MCX")
    _, kwargs = broker.get_option_chain.call_args
    assert kwargs["exchange"] == "MCX"


def test_contract_switch_guard_initial_switch():
    guard = ContractSwitchGuard()
    now = 100.0
    assert guard.should_switch("NIFTY 20 MAR 23400 CE", 80.0, now)
    assert guard.current_contract == "NIFTY 20 MAR 23400 CE"


def test_contract_switch_guard_blocks_when_open():
    guard = ContractSwitchGuard()
    guard.should_switch("A", 80.0, 100.0)
    guard.set_open_trade(True)
    assert guard.should_switch("B", 120.0, 500.0) is False


def test_contract_switch_guard_allows_after_time_and_delta():
    guard = ContractSwitchGuard()
    assert guard.should_switch("A", 50.0, 100.0)
    assert guard.should_switch("B", 70.0, 450.0) is True

