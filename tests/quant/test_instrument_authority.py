"""InstrumentRegistry is the only authority for root metadata.

Every consumer that used to keep its own NSE/MCX table must agree with
DEFAULT_REGISTRY. YAML cannot disagree. Unknown roots must not become MCX.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from quant.amt.session.scanner import OptionScannerService
from quant.amt.session.selector import OptionSelector
from quant.contracts.exchange_config import ExchangeConfig
from quant.contracts.instrument_registry import (
    DEFAULT_REGISTRY,
    UnknownInstrumentError,
)
from quant.contracts.timezones import MCX_SESSION_CLOSE, NSE_SESSION_CLOSE

_ROOT = Path(__file__).resolve().parents[2]


def test_registry_nickel_tick_and_cottoncandy_lot_are_exchange_series():
    assert DEFAULT_REGISTRY.resolve("NICKEL").tick_size == 1.0
    assert DEFAULT_REGISTRY.resolve("COTTONCANDY").lot_size == 25


def test_exchange_config_lot_tick_freeze_match_registry():
    nse = ExchangeConfig.for_exchange("NSE")
    mcx = ExchangeConfig.for_exchange("MCX")
    for spec in DEFAULT_REGISTRY.specs():
        cfg = mcx if spec.session_profile == "MCX" else nse
        assert spec.root in cfg.underlyings, spec.root
        assert cfg.get_lot_size(spec.root) == spec.lot_size, spec.root
        assert cfg.get_tick_size(spec.root) == spec.tick_size, spec.root
        assert cfg.get_freeze_limit(spec.root) == spec.freeze_limit, spec.root


def test_selector_lot_and_strike_match_registry():
    sel = OptionSelector()
    for spec in DEFAULT_REGISTRY.specs():
        assert sel._lot_size_for(spec.root) == spec.lot_size, spec.root
        assert sel._strike_interval(spec.root) == int(spec.strike_interval), spec.root


def test_scanner_uses_registry_dhan_exchange_not_mcx_default():
    assert OptionScannerService.dhan_exchange_for("SENSEX") == "BFO"
    assert OptionScannerService.dhan_exchange_for("BANKEX") == "BFO"
    assert OptionScannerService.dhan_exchange_for("NIFTY") == "NFO"
    assert OptionScannerService.dhan_exchange_for("CRUDEOIL") == "MCX"
    with pytest.raises(UnknownInstrumentError):
        OptionScannerService.dhan_exchange_for("UNKNOWN_THING")


def test_yaml_silverm_lot_matches_registry():
    path = _ROOT / "backend/config/strategies/mcx_options.yaml"
    data = yaml.safe_load(path.read_text())
    yaml_lot = data["exchanges"]["MCX"]["symbols"]["SILVERM"]["lot_size"]
    assert yaml_lot == DEFAULT_REGISTRY.resolve("SILVERM").lot_size == 5


def test_yaml_nse_session_close_is_real_exchange_close():
    path = _ROOT / "backend/config/base.yaml"
    data = yaml.safe_load(path.read_text())
    close = data["exchanges"]["NSE"]["session_close"]
    expected = NSE_SESSION_CLOSE.strftime("%H:%M")
    assert close == expected == "15:30"
    mcx_close = data["exchanges"]["MCX"]["session_close"]
    assert mcx_close == MCX_SESSION_CLOSE.strftime("%H:%M") == "23:30"


def test_loaded_mcx_config_agrees_with_registry():
    os.environ["GLASSYTRADE_ENV"] = "paper"
    os.environ["GLASSYTRADE_STRATEGY"] = "mcx_options"
    from app.config_models.loader import load_config

    cfg = load_config(
        config_dir=str(_ROOT / "backend/config"),
        strategy="mcx_options",
    )
    for ex in cfg.exchanges.values():
        for name, sym in ex.symbols.items():
            spec = DEFAULT_REGISTRY.try_resolve(name)
            if spec is None:
                continue
            assert sym.lot_size == spec.lot_size, name
            assert sym.tick_size == spec.tick_size, name
            assert int(sym.strike_interval) == int(spec.strike_interval), name


def test_coordinator_spawn_uses_symbol_session_profile():
    from quant.multi_engine import QuantCoordinator

    class _MD:
        def get_nearest_futures(self, *a, **k):
            return None

        def get_lot_size(self, symbol):
            return DEFAULT_REGISTRY.resolve(symbol).lot_size

    coord = QuantCoordinator(
        market_data=_MD(),
        config={"underlyings": ["CRUDEOIL"], "exchange": "NSE", "n": 1},
    )
    coord._feed = type("F", (), {"add_reader": staticmethod(lambda s: None)})()
    # LiveGateway needs a feed with next_tick plumbing — spawn via public helper
    engine_market = coord._session_profile_for("CRUDEOIL 19 AUG 6000 CALL")
    assert engine_market == "MCX"
    assert coord._session_profile_for("NIFTY 27 AUG 24500 CALL") == "NSE"
    assert coord._session_profile_for("SENSEX 28 AUG 81000 CALL") == "NSE"


def test_frontend_projection_has_no_legacy_underlying_authority():
    projection_root = _ROOT / "frontend" / "src" / "projection"
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in projection_root.glob("*.ts")
    )
    assert "MCX_UNDERLYINGS" not in sources
    assert "lot_size" not in sources


def test_unknown_root_does_not_default_tick_or_lot():
    with pytest.raises(UnknownInstrumentError):
        DEFAULT_REGISTRY.resolve("NIFTYNXT50")
    nse = ExchangeConfig.for_exchange("NSE")
    with pytest.raises(KeyError):
        nse.get_lot_size("NIFTYNXT50")


def test_resolve_lot_size_mcx_ignores_broker_dummy_one():
    from quant.multi_engine import QuantCoordinator

    class _DhanBrokerWithDummyLot:
        def get_lot_size(self, symbol):
            # Dhan scrip master reports 1.0 for all MCX derivatives
            return 1.0

    coord = QuantCoordinator(
        market_data=_DhanBrokerWithDummyLot(),
        config={"underlyings": ["GOLDM"], "exchange": "MCX", "n": 1},
    )
    assert coord._resolve_lot_size("GOLDM OCT FUT") == 10.0
    assert coord._resolve_lot_size("GOLDM 25 SEP 153000 PUT") == 10.0
    assert coord._resolve_lot_size("CRUDEOIL SEP FUT") == 100.0
    assert coord._resolve_lot_size("SILVERM NOV FUT") == 5.0
    assert coord._resolve_lot_size("NATURALGAS SEP FUT") == 1250.0
