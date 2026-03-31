
import asyncio
import logging
import sys
import os

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.domain.fabio_ai.services.option_scanner import OptionScannerService
from unittest.mock import MagicMock

async def test_fallback_selection():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("test_scanner")
    
    # Mock broker
    mock_broker = MagicMock()
    
    # Mock Option Chain for CRUDEOIL
    crude_chain = MagicMock()
    crude_chain.atm_strike = 6000
    crude_chain.spot_price = 6010
    crude_chain.expiry.date.return_value.isoformat.return_value = "2026-04-17"
    
    # Mock call/put maps
    ce_opt = MagicMock()
    ce_opt.symbol = "CRUDEOIL 17 APR 6000 CALL"
    ce_opt.ltp = 150.0
    ce_opt.oi = 1000
    ce_opt.volume = 500
    ce_opt.ask = 151.0
    ce_opt.bid = 149.0
    
    pe_opt = MagicMock()
    pe_opt.symbol = "CRUDEOIL 17 APR 6000 PUT"
    pe_opt.ltp = 140.0
    pe_opt.oi = 1200
    pe_opt.volume = 600
    pe_opt.ask = 141.0
    pe_opt.bid = 139.0
    
    crude_chain.calls = {6000.0: ce_opt}
    crude_chain.puts = {6000.0: pe_opt}
    
    # Mock Option Chain for NATURALGAS
    ng_chain = MagicMock()
    ng_chain.atm_strike = 200
    ng_chain.spot_price = 201
    ng_chain.expiry.date.return_value.isoformat.return_value = "2026-04-25"
    
    ng_ce = MagicMock()
    ng_ce.symbol = "NATURALGAS 25 APR 200 CALL"
    ng_ce.ltp = 15.0
    ng_ce.oi = 5000
    ng_ce.volume = 2000
    ng_ce.ask = 15.5
    ng_ce.bid = 14.5
    
    ng_pe = MagicMock()
    ng_pe.symbol = "NATURALGAS 25 APR 200 PUT"
    ng_pe.ltp = 12.0
    ng_pe.oi = 4500
    ng_pe.volume = 1800
    ng_pe.ask = 12.5
    ng_pe.bid = 11.5
    
    ng_chain.calls = {200.0: ng_ce}
    ng_chain.puts = {200.0: ng_pe}
    
    def side_effect(underlying, **kwargs):
        if underlying == "CRUDEOIL":
            return crude_chain
        if underlying == "NATURALGAS":
            return ng_chain
        return None
        
    mock_broker.get_option_chain.side_effect = side_effect
    
    scanner = OptionScannerService(mock_broker)
    
    # Test scan_top_n with momentum that will fail (trigger fallback)
    # We mock _detect_momentum to return NEUTRAL
    scanner._detect_momentum = MagicMock(return_value=("NEUTRAL", 0, "No momentum"))
    
    # We want to force it to go to fallback by making scores 0 or filters fail
    # Actually, if _detect_momentum is NEUTRAL, it doesn't mean it goes to fallback.
    # Fallback happens if 'final' is empty.
    # Let's make it go to fallback by mocking the main loop to produce no results.
    # Easiest way: Mock results.append to do nothing (or just use the fallback logic directly)
    
    logger.info("Running scan_top_n with expected zero results to trigger fallback...")
    
    # Trigger fallback by making strikes list empty or something
    # or just let it run and see if it picks multiple.
    
    # We need to make sure 'final' is empty.
    # In scan_top_n, 'results' is populated in the loop. 
    # Let's mock ltp to be outside range to filter everything out.
    ce_opt.ltp = 0
    pe_opt.ltp = 0
    ng_ce.ltp = 0
    ng_pe.ltp = 0
    
    # But in fallback, it checks ltp > 0 too.
    # So let's make it work in fallback:
    # 1. Main loop fails filters (e.g. min_oi)
    # 2. Fallback loop succeeds (ltp > 0)
    
    ce_opt.oi = 0 # Main loop filter
    pe_opt.oi = 0
    ng_ce.oi = 0
    ng_pe.oi = 0
    
    # Fallback loop only checks ltp > 0
    ce_opt.ltp = 150.0
    pe_opt.ltp = 140.0
    ng_ce.ltp = 15.0
    ng_pe.ltp = 12.0
    
    results = scanner.scan_top_n(
        n=4,
        underlyings=["CRUDEOIL", "NATURALGAS"],
        top_per_underlying=2
    )
    
    logger.info(f"Scanner returned {len(results)} contracts")
    for r in results:
        logger.info(f" - {r.symbol} ({r.option_type})")
        
    assert len(results) == 4, f"Expected 4 contracts (CE+PE for 2 underlyings), got {len(results)}"
    symbols = [r.symbol for r in results]
    assert "CRUDEOIL 17 APR 6000 CALL" in symbols
    assert "CRUDEOIL 17 APR 6000 PUT" in symbols
    assert "NATURALGAS 25 APR 200 CALL" in symbols
    assert "NATURALGAS 25 APR 200 PUT" in symbols
    
    logger.info("TEST PASSED: Fallback selected CE+PE for both underlyings!")

if __name__ == "__main__":
    asyncio.run(test_fallback_selection())
