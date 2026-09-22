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
    assert eng.last_snapshot is None
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


def test_last_snapshot_matches_dto_time_and_poc():
    store = SessionLevelStore()
    eng = AMTEngine(
        symbol="NIFTY",
        market="NSE",
        session_levels=store,
    )
    rows = []
    for i in range(5):
        price = 100.0 + i
        rows.append(
            {
                "time": f"2026-09-21T09:{15 + i * 5:02d}:00+05:30",
                "open": price,
                "high": price + 2.0,
                "low": price - 1.0,
                "close": price + 1.0,
                "volume": 100.0 * (i + 1),
                "delta": float((i + 1) * 10),
            }
        )
    for row in rows:
        vol = row["volume"]
        delta = row["delta"]
        eng.analyze(
            Bar(
                time=row["time"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=vol,
                buy_volume=(vol + delta) / 2.0,
                sell_volume=(vol - delta) / 2.0,
                delta=delta,
            )
        )

    assert eng.last_snapshot is not None
    assert eng.last_snapshot.asof_time == eng.last_amt_dto["time"]
    assert eng.last_snapshot.result.poc == eng.last_amt_dto["poc"]
    assert eng.last_snapshot.result.poc > 0
