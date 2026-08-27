# tests/quant/coordinator/test_strike_migration.py
import pytest
from unittest.mock import MagicMock
from quant.multi_engine import QuantCoordinator
from quant.bars import Bar


def test_coordinator_migrates_drifted_strikes():
    """When an option strike drifts > 2.5 steps away from spot, check_and_migrate_drifted_strikes flags it and rescans."""
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord._lock = MagicMock()
    coord._lifecycle_lock = MagicMock()
    
    # Mock futures engine with spot = 25000 (NIFTY step = 50)
    mock_fut_engine = MagicMock()
    mock_fut_engine._aggregator.current_bar = Bar(
        time="t1", open=25000.0, high=25000.0, low=25000.0, close=25000.0,
        volume=100, buy_volume=50, sell_volume=50, delta=0, oi=1000, vwap=25000.0,
    )
    
    # Mock option engine with old strike 24200 (drift = 800 pts > 2.5 * 50 = 125 pts)
    mock_opt_engine = MagicMock()
    mock_opt_engine._position = None
    
    coord._engines = {
        "NIFTY SEP FUT": mock_fut_engine,
        "NIFTY 1 SEP 24200 CALL": mock_opt_engine,
    }
    coord.market_data = MagicMock()
    coord.rescan = MagicMock(return_value=["NIFTY SEP FUT", "NIFTY 1 SEP 25000 CALL"])
    
    drifted = coord.check_and_migrate_drifted_strikes(max_drift_steps=2.5)
    
    assert "NIFTY 1 SEP 24200 CALL" in drifted
    coord.rescan.assert_called_once()
