# tests/quant/coordinator/test_strike_migration.py
from types import SimpleNamespace
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
    mock_opt_engine.state = SimpleNamespace(position=None, pyramids=())
    
    coord._engines = {
        "NIFTY SEP FUT": mock_fut_engine,
        "NIFTY 1 SEP 24200 CALL": mock_opt_engine,
    }
    coord.market_data = MagicMock()
    coord.rescan = MagicMock(return_value=["NIFTY SEP FUT", "NIFTY 1 SEP 25000 CALL"])
    
    drifted = coord.check_and_migrate_drifted_strikes(max_drift_steps=2.5)
    
    assert "NIFTY 1 SEP 24200 CALL" in drifted
    coord.rescan.assert_called_once()


def test_extract_option_strike():
    from quant.multi_engine import extract_option_strike

    # Spaced formats
    assert extract_option_strike("NIFTY 1 SEP 24200 CALL") == 24200.0
    assert extract_option_strike("NIFTY 27 MAR 23500 CE") == 23500.0
    assert extract_option_strike("CRUDEOIL 19 MAR 6800.5 PE") == 6800.5
    assert extract_option_strike("BANKNIFTY 28 AUG 51200 PUT") == 51200.0

    # Compact monthly formats
    assert extract_option_strike("NIFTY24AUG23500CE") == 23500.0
    assert extract_option_strike("CRUDEOIL24MAR6800PE") == 6800.0
    assert extract_option_strike("BANKNIFTY24SEP51000CE") == 51000.0

    # Compact weekly formats
    assert extract_option_strike("NIFTY2482823500CE") == 23500.0
    assert extract_option_strike("BANKNIFTY24O2851000PE") == 51000.0

    # Prefixed formats
    assert extract_option_strike("NSE:NIFTY24AUG23500CE") == 23500.0
    assert extract_option_strike("MCX:CRUDEOIL 19 MAR 6800 PE") == 6800.0

    # Hyphenated / Delimited
    assert extract_option_strike("NIFTY-27MAR24-23500-CE") == 23500.0
    assert extract_option_strike("CRUDEOIL_6800_CE") == 6800.0

    # Non-options / invalid
    assert extract_option_strike("NIFTY SEP FUT") is None
    assert extract_option_strike("CRUDEOIL FUT") is None
    assert extract_option_strike("") is None
    assert extract_option_strike(None) is None


def test_coordinator_migrates_compact_drifted_strikes():
    """Compact option symbols without spaces are correctly parsed and migrated on drift."""
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord._lock = MagicMock()
    coord._lifecycle_lock = MagicMock()

    mock_fut_engine = MagicMock()
    mock_fut_engine._aggregator.current_bar = Bar(
        time="t1", open=25000.0, high=25000.0, low=25000.0, close=25000.0,
        volume=100, buy_volume=50, sell_volume=50, delta=0, oi=1000, vwap=25000.0,
    )

    mock_opt_engine = MagicMock()
    mock_opt_engine.state = SimpleNamespace(position=None, pyramids=())

    coord._engines = {
        "NIFTY SEP FUT": mock_fut_engine,
        "NIFTY24AUG24200CE": mock_opt_engine,
    }
    coord.market_data = MagicMock()
    coord.rescan = MagicMock(return_value=["NIFTY SEP FUT", "NIFTY24AUG25000CE"])

    drifted = coord.check_and_migrate_drifted_strikes(max_drift_steps=2.5)

    assert "NIFTY24AUG24200CE" in drifted
    coord.rescan.assert_called_once()


def test_coordinator_skips_drifted_strike_with_open_position():
    """A drifted strike holding an open position is NEVER migrated/rescanned
    (the real position authority — the folded EngineState)."""
    coord = QuantCoordinator.__new__(QuantCoordinator)
    coord._lock = MagicMock()
    coord._lifecycle_lock = MagicMock()

    mock_fut_engine = MagicMock()
    mock_fut_engine._aggregator.current_bar = Bar(
        time="t1", open=25000.0, high=25000.0, low=25000.0, close=25000.0,
        volume=100, buy_volume=50, sell_volume=50, delta=0, oi=1000, vwap=25000.0,
    )

    mock_opt_engine = MagicMock()
    mock_opt_engine.state = SimpleNamespace(position=object())  # open book

    coord._engines = {
        "NIFTY SEP FUT": mock_fut_engine,
        "NIFTY 1 SEP 24200 CALL": mock_opt_engine,
    }
    coord.market_data = MagicMock()
    coord.rescan = MagicMock()

    drifted = coord.check_and_migrate_drifted_strikes(max_drift_steps=2.5)

    assert drifted == [], "open book must never be migrated away"
    coord.rescan.assert_not_called()

