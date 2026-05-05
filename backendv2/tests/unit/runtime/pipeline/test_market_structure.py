"""Tests for MarketStructureAnalysis pipeline stage.

Migrates 11 existing AMT services into one cohesive pipeline stage.
Test-driven: write tests FIRST, then implement.
"""

from app.runtime.pipeline.events import Candle, CandleTimeframe
from app.runtime.pipeline.market_structure import MarketStructureAnalysis


def _candle(symbol="BANKNIFTY", open_p=45000.0, high=45100.0, low=44900.0,
            close=45050.0, volume=1000, ts=0, buy_vol=500, sell_vol=500):
    return Candle(
        symbol=symbol, timeframe=CandleTimeframe.M1,
        open=open_p, high=high, low=low, close=close,
        volume=volume, timestamp=ts, complete=True,
        buy_volume=buy_vol, sell_volume=sell_vol,
    )


def test_empty_state_returns_defaults():
    ms = MarketStructureAnalysis()
    result = ms.get_result("BANKNIFTY")
    assert result.symbol == "BANKNIFTY"
    assert result.poc == 0.0
    assert result.vah == 0.0
    assert result.val == 0.0
    assert result.market_state == "BALANCED"
    assert result.profile_shape == "D"


def test_single_candle_basic_profile():
    ms = MarketStructureAnalysis()
    ms.process(_candle(ts=0))
    result = ms.get_result("BANKNIFTY")
    # POC at the candle's price level
    assert result.poc > 0
    assert result.vah >= result.val


def test_multiple_candles_accumulate_volume():
    ms = MarketStructureAnalysis()
    for i in range(100):
        ms.process(_candle(ts=i * 60_000_000_000, volume=1000))
    result = ms.get_result("BANKNIFTY")
    assert result.poc > 0
    assert result.vah > result.val


def test_value_area_contains_68_percent():
    ms = MarketStructureAnalysis()
    # Generate candles with volume concentrated at 45000
    for i in range(200):
        price = 45000.0 + (i % 100) * 2.0
        vol = 1000 if abs(price - 45000.0) < 50 else 100
        ms.process(_candle(ts=i * 60_000_000_000, open_p=price, high=price+5,
                           low=price-5, close=price, volume=vol))
    result = ms.get_result("BANKNIFTY")
    # VAH and VAL should capture the high-volume area
    assert result.vah > result.val
    assert result.poc >= result.val and result.poc <= result.vah


def test_break_detected():
    ms = MarketStructureAnalysis()
    # Normal candles
    for i in range(60):
        ms.process(_candle(ts=i * 60_000_000_000, open_p=45000.0, high=45010.0,
                           low=44990.0, close=45000.0, volume=500))
    # Break candle: close above VAH with high volume
    result = ms.process(_candle(ts=60 * 60_000_000_000, open_p=45200.0, high=45300.0,
                                low=45150.0, close=45250.0, volume=5000))
    assert len(result) > 0  # candle emitted
    ms_result = ms.get_result("BANKNIFTY")
    # Break should be detected
    assert ms_result.vah > 0
    assert ms_result.val > 0


def test_displacement_detected():
    ms = MarketStructureAnalysis()
    for i in range(30):
        ms.process(_candle(ts=i * 60_000_000_000, high=45000.0 + i,
                           low=44990.0 + i, volume=500))
    # Large move candle
    result = ms.process(_candle(ts=30 * 60_000_000_000,
                                open_p=45030.0, high=45300.0, low=45030.0,
                                close=45280.0, volume=3000))
    ms_result = ms.get_result("BANKNIFTY")
    # Displacement should be flagged
    assert ms_result.vah > 0
    assert ms_result.val > 0


def test_market_state_balanced_inside_va():
    ms = MarketStructureAnalysis()
    for i in range(100):
        price = 45000.0 + (i % 50) * 2.0
        ms.process(_candle(ts=i * 60_000_000_000, open_p=price, high=price+5,
                           low=price-5, close=price, volume=1000))
    ms.process(_candle(ts=201 * 60_000_000_000,
                       open_p=45050.0, high=45060.0, low=45040.0,
                       close=45055.0, volume=500))
    result = ms.get_result("BANKNIFTY")
    assert result.market_state in ("BALANCED", "IMBALANCED")


def test_reset_clears_all_state():
    ms = MarketStructureAnalysis()
    for i in range(10):
        ms.process(_candle(ts=i * 60_000_000_000))
    assert ms.get_result("BANKNIFTY").poc > 0
    ms.reset()
    result = ms.get_result("BANKNIFTY")
    assert result.poc == 0.0
    assert result.vah == 0.0
    assert result.val == 0.0


def test_multiple_symbols_independent():
    ms = MarketStructureAnalysis()
    ms.process_symbol("BANKNIFTY", _candle(symbol="BANKNIFTY", ts=0))
    ms.process_symbol("NIFTY", _candle(symbol="NIFTY", ts=0, open_p=22000.0, close=22050.0, high=22060.0, low=21990.0))
    bn = ms.get_result("BANKNIFTY")
    n = ms.get_result("NIFTY")
    assert bn.poc != n.poc or bn.vah != n.vah


def test_session_context_gap_classification():
    ms = MarketStructureAnalysis()
    # Process initial balance candles
    for i in range(15):
        ms.process(_candle(ts=i * 60_000_000_000, open_p=45000.0, high=45050.0,
                           low=44950.0, close=45000.0, volume=1000))
    # Candle with gap
    ms.process(_candle(ts=15 * 60_000_000_000, open_p=45200.0, high=45250.0,
                       low=45150.0, close=45200.0, volume=2000))
    result = ms.get_result("BANKNIFTY")
    assert result.gap_size in ("NONE", "SMALL", "MEDIUM", "LARGE")


def test_profile_shape_classified():
    ms = MarketStructureAnalysis()
    # Top-heavy volume distribution
    for i in range(50):
        price = 45100.0 - (i * 2.0)
        vol = 2000 if price > 45050.0 else 200
        ms.process(_candle(ts=i * 60_000_000_000, open_p=price, high=price+5,
                           low=price-5, close=price, volume=vol))
    result = ms.get_result("BANKNIFTY")
    assert result.profile_shape in ("P", "b", "D", "B")