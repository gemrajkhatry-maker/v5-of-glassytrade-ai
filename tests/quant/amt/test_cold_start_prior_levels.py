# tests/quant/amt/test_cold_start_prior_levels.py
import pytest
from unittest.mock import MagicMock
from quant.amt_engine import AMTEngine
from quant.session_levels import SessionLevelStore
from quant.contracts.timezones import IST


class _MultiDayHistorySource:
    """Returns 2 days of historical candles."""
    def __init__(self):
        self.candles = []
        # Day 1: 2026-08-26 (yesterday) - 10 candles
        for i in range(10):
            t = f"2026-08-26T1{i:02d}:00:00+05:30"
            self.candles.append({
                "time": t, "open": 24000.0 + i, "high": 24050.0 + i,
                "low": 23950.0 + i, "close": 24020.0 + i, "volume": 1000 + i * 100,
                "vwap": 24010.0, "takerBuyVolume": 600, "delta": 200,
            })
        # Day 2: 2026-08-27 (today) - 3 candles
        for i in range(3):
            t = f"2026-08-27T09:{15 + i * 5:02d}:00+05:30"
            self.candles.append({
                "time": t, "open": 24100.0 + i, "high": 24150.0 + i,
                "low": 24080.0 + i, "close": 24120.0 + i, "volume": 500,
                "vwap": 24110.0, "takerBuyVolume": 250, "delta": 0,
            })

    def fetch_history(self, symbol, interval="5m", limit=500):
        return list(self.candles)


def test_cold_start_seeds_prior_session_levels():
    """When engine boots with empty prior levels, it extracts yesterday's POC/VAH/VAL from history."""
    source = _MultiDayHistorySource()
    store = SessionLevelStore()
    engine = AMTEngine(
        symbol="NIFTY SEP FUT",
        market="NSE",
        session_levels=store,
        history_source=source,
    )
    assert engine._prior.get("poc", 0.0) == 0.0
    
    engine.seed()
    
    # Verify prior POC was extracted from 2026-08-26 candles
    assert engine._prior.get("poc", 0.0) > 0.0
    assert engine._prior.get("vah", 0.0) > 0.0
    assert engine._prior.get("val", 0.0) > 0.0
    assert len(engine._amt_candles) == 3  # Today's session candles only in active profile
