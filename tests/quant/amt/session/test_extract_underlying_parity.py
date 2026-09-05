"""Parity: every symbol→underlying path must agree with ExchangeConfig — the
canonical parser used by runtime entry sizing (quant/runtime.py:_underlying).

Pins (Task 6, simplification refactor):
  - UnderlyingFuturesProvider._extract_underlying delegates to
    ExchangeConfig.extract_underlying (NSE → MCX) with a first-token
    fallback retained for behavior compatibility.
  - SymbolRegistry._extract_underlying is registry-specific (prefix-match
    over injected underlying sets, consulted only when DEFAULT_REGISTRY
    resolution fails) yet agrees with the canonical parser on every
    realistic contract format below.
"""

from __future__ import annotations

import pytest

from quant.amt.session.futures_provider import UnderlyingFuturesProvider
from quant.amt.session.symbol_registry import SymbolRegistry
from quant.contracts.exchange_config import ExchangeConfig

SYMBOLS = [
    "NIFTY 27 FEB 25500 CE",
    "BANKNIFTY 05 SEP 51000 PE",
    "CRUDEOIL 17 AUG 6100 CALL",
    "NATURALGAS SEP FUT",
    "NIFTY-27FEB-25500-CE",
    "NIFTY27FEB25500CE",
    "SILVERM 24 SEP 235000 PUT",
]


def canonical_underlying(symbol: str) -> str:
    """ExchangeConfig result exactly as futures_provider consumes it:
    first non-empty among NSE then MCX."""
    for ex in ("NSE", "MCX"):
        underlying = ExchangeConfig.for_exchange(ex).extract_underlying(symbol)
        if underlying:
            return underlying
    return ""


@pytest.fixture(scope="module")
def provider() -> UnderlyingFuturesProvider:
    return UnderlyingFuturesProvider()


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_futures_provider_matches_exchange_config(
    provider: UnderlyingFuturesProvider, symbol: str
):
    assert provider._extract_underlying(symbol) == canonical_underlying(symbol)


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_symbol_registry_matches_exchange_config(symbol: str):
    registry = SymbolRegistry()
    assert registry._extract_underlying(symbol) == canonical_underlying(symbol)


def test_futures_provider_empty_symbol_fallback(
    provider: UnderlyingFuturesProvider,
):
    """Degenerate input: both exchange configs return "" and the provider's
    first-token fallback also returns "". Documents the fallback path is
    reachable and behavior-identical for the only input that reaches it."""
    assert provider._extract_underlying("") == canonical_underlying("") == ""
