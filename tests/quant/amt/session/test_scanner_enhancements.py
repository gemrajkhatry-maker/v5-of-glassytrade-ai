# tests/quant/amt/session/test_scanner_enhancements.py
"""Tests for Option Scanner Enhancements: 0DTE retention, CE/PE balance, spot drift."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from quant.amt.session.scanner import OptionScannerService
from quant.multi_engine import QuantCoordinator


def test_0dte_expiry_retained_on_same_day():
    """Verify that contracts expiring today (0DTE) are NOT skipped as past."""
    broker = MagicMock()
    today = date.today()
    mock_chain = MagicMock()
    mock_chain.expiry = today
    mock_chain.atm_strike = 24200
    mock_chain.spot_price = 24200.0
    mock_chain.strikes = [24200]
    
    ce_opt = MagicMock(
        symbol=f"NIFTY {today.day} {today.strftime('%b').upper()} 24200 CALL",
        strike=24200, ltp=150.0, volume=100000, oi=500000, bid=149.5, ask=150.5,
    )
    pe_opt = MagicMock(
        symbol=f"NIFTY {today.day} {today.strftime('%b').upper()} 24200 PUT",
        strike=24200, ltp=120.0, volume=100000, oi=500000, bid=119.5, ask=120.5,
    )
    mock_chain.calls = {24200: ce_opt}
    mock_chain.puts = {24200: pe_opt}
    
    broker.get_option_chain.return_value = mock_chain
    
    scanner = OptionScannerService(broker)
    results = scanner.scan_top_n(n=2, underlyings=["NIFTY"], exchange="NFO")
    
    assert len(results) == 2
    assert results[0].expiry == today.isoformat()
    # broker should only have been called with expiry_index=0, never advanced to 1
    broker.get_option_chain.assert_called_once_with(underlying="NIFTY", exchange="NFO", expiry_index=0)


def test_interleaved_balanced_ce_pe_selection():
    """Verify that scan_top_n returns balanced CE and PE pairs per underlying."""
    broker = MagicMock()
    today = date.today()
    mock_chain = MagicMock()
    mock_chain.expiry = today
    mock_chain.atm_strike = 24200
    mock_chain.spot_price = 24200.0
    mock_chain.strikes = [24200]
    
    ce_opt = MagicMock(
        symbol="NIFTY 25 AUG 24200 CALL",
        strike=24200, ltp=150.0, volume=100000, oi=500000, bid=149.5, ask=150.5,
    )
    pe_opt = MagicMock(
        symbol="NIFTY 25 AUG 24200 PUT",
        strike=24200, ltp=120.0, volume=100000, oi=500000, bid=119.5, ask=120.5,
    )
    mock_chain.calls = {24200: ce_opt}
    mock_chain.puts = {24200: pe_opt}
    broker.get_option_chain.return_value = mock_chain
    
    scanner = OptionScannerService(broker)
    results = scanner.scan_top_n(n=2, underlyings=["NIFTY"], exchange="NFO", top_per_underlying=2)
    
    assert len(results) == 2
    types = {r.option_type for r in results}
    assert types == {"CE", "PE"}


def test_quant_coordinator_check_spot_drift():
    """Verify spot drift detection when price moves > 1.5 strike intervals away."""
    market_data = MagicMock()
    coord = QuantCoordinator(market_data, config={"underlyings": ["NIFTY"]})
    
    # Mock active engines for NIFTY 24200 CALL and PUT
    coord._engines = {
        "NIFTY AUG FUT": MagicMock(),
        "NIFTY 25 AUG 24200 CALL": MagicMock(),
        "NIFTY 25 AUG 24200 PUT": MagicMock(),
    }
    
    # NIFTY step is 50. 1.5 * step = 75.
    # At 24250 (within 50 pts): no drift
    assert coord.check_spot_drift("NIFTY", 24250.0) is False
    
    # At 24300 (> 75 pts above 24200): drift detected
    assert coord.check_spot_drift("NIFTY", 24300.0) is True
    
    # At 24100 (> 75 pts below 24200): drift detected
    assert coord.check_spot_drift("NIFTY", 24100.0) is True
