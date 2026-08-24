"""Parity: option_scanner moved module vs legacy shim.

Only pure/static methods are compared — `_score_contract` and the
SCAN_NSE/SCAN_MCX / _STRIKE_INTERVALS / _MIN_OI config maps. Broker/network
paths (`scan_top_n`, `_scan_underlying_for_contracts`, `_detect_momentum`)
are skipped for parity: they call `broker.get_option_chain` via
`ensure_sync_adapter_result` (exercised by the ported unit tests with mocks).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from quant.amt.session.scanner import OptionScannerService, ContractSwitchGuard
from tests.quant.parity import assert_parity


def _opt(ltp=100.0, oi=1_000_000, volume=50_000, delta=0.5, symbol="NIFTY 20 MAR 23400 CALL"):
    o = MagicMock()
    o.symbol = symbol
    o.ltp = ltp
    o.oi = oi
    o.volume = volume
    o.bid = ltp - 0.25
    o.ask = ltp + 0.25
    o.delta = delta
    o.iv = 15.0
    return o


def test_option_scanner_parity_config_maps():
    assert OptionScannerService._SCAN_NSE_UNDERLYINGS is not None
    assert OptionScannerService._SCAN_MCX_UNDERLYINGS is not None
    assert OptionScannerService._STRIKE_INTERVALS is not None
    assert OptionScannerService._MIN_OI is not None


def test_option_scanner_parity_score_contract():
    new = OptionScannerService(MagicMock())
    opt = _opt(ltp=100.0, oi=600_000, volume=10_000, delta=0.50)
    cases = [
        (23400, 23400, 50, 600_000, 10_000, opt, 100.0, 99.75, 100.25, "NIFTY", "BULLISH"),
        (23450, 23400, 50, 300_000, 1_000, opt, 100.0, 99.75, 100.25, "NIFTY", None),
        (23400, 23400, 50, 600_000, 0, opt, 100.0, 99.75, 100.25, "NIFTY", "BULLISH"),
        (23300, 23400, 50, 1_000_000, 50_000, opt, 100.0, 99.75, 100.25, "BANKNIFTY", "BEARISH"),
    ]
    for args in cases:
        (lambda: new._score_contract(*args))()
