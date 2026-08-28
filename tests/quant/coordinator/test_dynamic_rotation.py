"""Tests for dynamic rotation of dead/drifted option symbols in QuantCoordinator."""

import pytest
from unittest.mock import MagicMock, patch
from quant.multi_engine import QuantCoordinator
from quant.bars import Bar
from quant.amt.session.scanner import ScanResult


def test_rotate_dead_symbols_skips_futures():
    """Futures underlyings are foundational macro feeds and must NEVER be rotated."""
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord._lock = MagicMock()
    coord._lifecycle_lock = MagicMock()
    coord._stop = MagicMock()
    coord._stop.is_set.return_value = False
    coord.config = {"exchange": "NSE"}

    mock_fut = MagicMock()
    coord._engines = {"NIFTY SEP FUT": mock_fut}

    rotated = coord.check_and_rotate_dead_symbols()
    assert rotated == []


def test_rotate_dead_symbols_skips_open_positions():
    """Option contracts with active open positions must NEVER be rotated."""
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord._lock = MagicMock()
    coord._lifecycle_lock = MagicMock()
    coord._stop = MagicMock()
    coord._stop.is_set.return_value = False
    coord.config = {"exchange": "NSE"}

    mock_opt = MagicMock()
    mock_opt._position = MagicMock()  # Active position!

    coord._engines = {"NIFTY 1 SEP 24100 PUT": mock_opt}

    rotated = coord.check_and_rotate_dead_symbols()
    assert rotated == []


@patch("quant.amt.session.symbol_registry.is_market_open", return_value=True)
@patch("quant.amt.session.scanner.OptionScannerService.scan_top_n")
def test_rotate_dead_symbols_swaps_drifted_strike(mock_scan, mock_open):
    """When an option strike drifts > 2.5 steps from spot, it is swapped for an active ATM contract."""
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord._lock = MagicMock()
    coord._lifecycle_lock = MagicMock()
    coord._stop = MagicMock()
    coord._stop.is_set.return_value = False
    coord.config = {"exchange": "NSE", "expiry_index": 0, "strikes_around_atm": 3}
    coord.market_data = MagicMock()

    # Futures spot at 24500 (NIFTY step = 50)
    mock_fut = MagicMock()
    mock_fut._aggregator.current_bar = Bar(
        time="t1", open=24500.0, high=24500.0, low=24500.0, close=24500.0,
        volume=100, buy_volume=50, sell_volume=50, delta=0, oi=1000, vwap=24500.0,
    )

    # Option strike at 24100 (drift = 400 pts > 2.5 * 50 = 125 pts)
    mock_opt = MagicMock()
    mock_opt._position = None
    mock_opt._market = "NSE"
    mock_opt._last_tick_wall = 0.0

    coord._engines = {
        "NIFTY SEP FUT": mock_fut,
        "NIFTY 1 SEP 24100 PUT": mock_opt,
    }

    # Scanner returns replacement ATM contract
    mock_scan.return_value = [
        ScanResult(
            symbol="NIFTY 1 SEP 24500 PUT",
            underlying="NIFTY",
            strike=24500.0,
            option_type="PE",
            expiry="2026-09-01",
            ltp=120.0,
            oi=50000,
            volume=20000,
            spread=0.5,
            score=85.0,
        ),
    ]

    coord.switch_symbol = MagicMock(return_value=True)

    rotated = coord.check_and_rotate_dead_symbols(max_drift_steps=2.5)

    assert len(rotated) == 1
    assert rotated[0] == ("NIFTY 1 SEP 24100 PUT", "NIFTY 1 SEP 24500 PUT")
    coord.switch_symbol.assert_called_once_with("NIFTY 1 SEP 24100 PUT", "NIFTY 1 SEP 24500 PUT")
