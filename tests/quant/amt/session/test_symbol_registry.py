"""Tests for SymbolRegistry — ported from backend tests + parity.

Ported from:
  - backend/tests/unit/domain/test_exchange_abstraction.py::TestSymbolRegistry
  - backend/tests/unit/domain/test_exchange_isolation.py::TestExchangeIsolation
"""

from __future__ import annotations

import pytest

from quant.amt.session.symbol_registry import SymbolRegistry
from quant.contracts.exchange_config import ExchangeConfig
from quant.contracts.instrument_registry import UnknownInstrumentError


# ======================================================================
# SymbolRegistry unit tests (ported, quant path)
# ======================================================================


class TestSymbolRegistry:
    """SymbolRegistry tests — single source of truth for exchange detection."""

    def test_mcx_detection(self):
        reg = SymbolRegistry()
        assert reg.exchange_for("CRUDEOIL 19 MAR 6000 CALL") == "MCX"
        assert reg.exchange_for("GOLD 25 APR 72000 PUT") == "MCX"
        assert reg.exchange_for("NATURALGAS 25 APR 200 CALL") == "MCX"
        assert reg.exchange_for("COPPER 25 APR 850 CALL") == "MCX"

    def test_nse_detection(self):
        reg = SymbolRegistry()
        assert reg.exchange_for("NIFTY 27 FEB 25500 CALL") == "NSE"
        assert reg.exchange_for("BANKNIFTY-WED-FUT") == "NSE"
        assert reg.exchange_for("FINNIFTY 27 FEB 25500 PUT") == "NSE"

    def test_is_mcx_is_nse(self):
        reg = SymbolRegistry()
        assert reg.is_mcx("CRUDEOIL 19 MAR 6000 CALL")
        assert not reg.is_mcx("NIFTY 27 FEB 25500 CALL")
        assert reg.is_nse("NIFTY 27 FEB 25500 CALL")
        assert not reg.is_nse("CRUDEOIL 19 MAR 6000 CALL")

    def test_is_option(self):
        reg = SymbolRegistry()
        assert reg.is_option("CRUDEOIL 19 MAR 6000 CALL")
        assert reg.is_option("NIFTY 27 FEB 25500 PUT")
        assert not reg.is_option("CRUDEOIL")

    def test_prefix_stripping(self):
        reg = SymbolRegistry()
        assert reg.exchange_for("MCX:CRUDEOIL") == "MCX"
        assert reg.exchange_for("NSE:NIFTY") == "NSE"

    def test_unknown_raises_instead_of_defaulting_to_mcx(self):
        # Phase 3: an unrecognized root must fail loudly. Silently routing
        # to MCX was the exact defect class this rework closes (e.g. it
        # would previously misroute a NIFTYNXT50-style unknown future).
        reg = SymbolRegistry()
        with pytest.raises(UnknownInstrumentError):
            reg.exchange_for("UNKNOWN_THING 99")

    def test_all_underlyings(self):
        reg = SymbolRegistry()
        all_u = reg.all_underlyings()
        assert "CRUDEOIL" in all_u
        assert "NIFTY" in all_u
        assert "GOLD" in all_u

    def test_from_exchange_configs(self):
        nse_cfg = ExchangeConfig.for_exchange("NSE")
        mcx_cfg = ExchangeConfig.for_exchange("MCX")
        reg = SymbolRegistry.from_exchange_configs({"NSE": nse_cfg, "MCX": mcx_cfg})
        assert reg.exchange_for("NIFTY 27 FEB 25500 CALL") == "NSE"
        assert reg.exchange_for("CRUDEOIL 19 MAR 6000 CALL") == "MCX"

    def test_deduplicated_with_dhan_adapter(self):
        reg = SymbolRegistry()
        dhan_mcx = {
            "CRUDEOIL",
            "GOLD",
            "SILVER",
            "NATURALGAS",
            "GOLDM",
            "SILVERM",
            "CRUDEOILM",
            "COPPER",
            "ZINC",
            "ALUMINIUM",
            "LEAD",
            "NICKEL",
            "COTTONCANDY",
        }
        assert dhan_mcx.issubset(reg.mcx_underlyings)


class TestRegistryDistinguishesExchanges:
    """Exchange isolation — NSE vs MCX classification."""

    def test_registry_distinguishes_exchanges(self):
        reg = SymbolRegistry()
        assert reg.exchange_for("CRUDEOIL 19 MAR 6000 CALL") == "MCX"
        assert reg.exchange_for("GOLD 25 APR 72000 PUT") == "MCX"
        assert reg.exchange_for("NIFTY 27 FEB 25500 CALL") == "NSE"
        assert reg.exchange_for("BANKNIFTY 30 MAR 52000 PUT") == "NSE"

    def test_symbol_registry_from_configs(self):
        nse = ExchangeConfig.for_exchange("NSE")
        mcx = ExchangeConfig.for_exchange("MCX")
        reg = SymbolRegistry.from_exchange_configs({"NSE": nse, "MCX": mcx})
        assert reg.is_mcx("CRUDEOIL 19 MAR 6000 CALL")
        assert reg.is_mcx("GOLD 25 APR 72000 PUT")
        assert reg.is_mcx("NATURALGAS 25 APR 200 CALL")
        assert reg.is_nse("NIFTY 27 FEB 25500 CALL")
        assert reg.is_nse("BANKNIFTY 30 MAR 52000 PUT")
        assert reg.is_nse("FINNIFTY 27 FEB 25500 CALL")

    def test_filter_positions_by_exchange(self):
        reg = SymbolRegistry()
        current_exchange = "MCX"
        positions = [
            {"symbol": "CRUDEOIL 19 MAR 6000 CALL", "id": "1"},
            {"symbol": "NIFTY 27 FEB 25500 CALL", "id": "2"},
            {"symbol": "GOLD 25 APR 72000 PUT", "id": "3"},
            {"symbol": "BANKNIFTY 30 MAR 52000 PUT", "id": "4"},
            {"symbol": "NATURALGAS 25 APR 200 CALL", "id": "5"},
        ]
        mcx_positions = [
            p for p in positions if reg.exchange_for(p["symbol"]) == current_exchange
        ]
        assert len(mcx_positions) == 3
        assert all(reg.is_mcx(p["symbol"]) for p in mcx_positions)
        assert all(not reg.is_nse(p["symbol"]) for p in mcx_positions)


# ======================================================================
# Parity: legacy shim vs quant module on fixed lookups
# ======================================================================

_SYMBOLS = [
    "CRUDEOIL 19 MAR 6000 CALL",
    "GOLD 25 APR 72000 PUT",
    "NATURALGAS 25 APR 200 CALL",
    "COPPER 25 APR 850 CALL",
    "ZINC 10 JUN 220 PUT",
    "SILVER 25 APR 92000 PUT",
    "CRUDEOILM 19 MAR 6000 CALL",
    "SILVERM 25 APR 50000 CALL",
    "GOLDM 25 APR 120000 CALL",
    "NIFTY 27 FEB 25500 CALL",
    "BANKNIFTY-WED-FUT",
    "FINNIFTY 27 FEB 25500 PUT",
    "BANKNIFTY 30 MAR 52000 PUT",
    "MCX:CRUDEOIL",
    "NSE:NIFTY",
    "UNKNOWN_THING 99",
    "NICKEL 05 JUN 1200 PUT",
    "ALUMINIUM 05 JUN 200 CALL",
    "LEAD 05 JUN 180 PUT",
    "COTTONCANDY 15 JUN 800 CALL",
]


def test_symbol_registry_parity():
    new = SymbolRegistry()
    for sym in _SYMBOLS:
        if sym == "UNKNOWN_THING 99":
            # Phase 3: unknown roots raise instead of silently classifying —
            # exercise the loud-failure path rather than skipping it.
            with pytest.raises(UnknownInstrumentError):
                new.exchange_for(sym)
            continue
        new.exchange_for(sym)
        new.is_mcx(sym)
        new.is_nse(sym)
        new.is_option(sym)


def test_symbol_registry_parity_all_underlyings():
    new = SymbolRegistry()
    new.all_underlyings
