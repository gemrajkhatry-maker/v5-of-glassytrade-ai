# tests/quant/amt/test_amt_engine_properties.py
import pytest
from quant.amt_engine import AMTEngine
from quant.session_levels import SessionLevelStore
from quant.contracts.value_objects import FloatOHLC
from quant.bars import Bar


def test_amt_engine_properties_initial_state():
    store = SessionLevelStore()
    eng = AMTEngine(
        symbol="NIFTY 1 SEP 25000 CALL",
        market="NSE",
        session_levels=store,
    )

    assert eng.warm_bars == 0
    assert eng.last_amt_dto is None
    assert eng.last_bar is None


def test_amt_engine_properties_with_candles():
    store = SessionLevelStore()
    eng = AMTEngine(
        symbol="NIFTY 1 SEP 25000 CALL",
        market="NSE",
        session_levels=store,
    )

    eng._warm_bars = 5
    dto = {"marketState": "BALANCED", "poc": 25000.0}
    eng._last_amt_dto = dto
    eng._amt_candles.append(
        FloatOHLC(
            time="2026-08-28T09:15:00Z",
            open=25000.0,
            high=25050.0,
            low=24950.0,
            close=25020.0,
            volume=1000.0,
            vwap=25010.0,
            taker_buy_volume=600.0,
            delta=200.0,
        )
    )

    assert eng.warm_bars == 5
    assert eng.last_amt_dto == dto
    bar = eng.last_bar
    assert isinstance(bar, Bar)
    assert bar.close == 25020.0
    assert bar.time == "2026-08-28T09:15:00Z"
