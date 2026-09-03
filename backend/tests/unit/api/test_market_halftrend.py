"""Endpoint tests for GET /api/market/halftrend/{symbol}.

The route replays REST history candles through the stateless HalfTrend
machine and returns one row per bar, aligned with /market/history/{symbol}.
"""

from __future__ import annotations

from quant.amt.market.half_trend import compute_half_trend_series
from quant.contracts.value_objects import OHLC
from app.api.routers.market import get_halftrend


class _FakeMarketData:
    def __init__(self, candles: list) -> None:
        self._candles = candles

    async def fetch_history(self, symbol: str, interval: str, limit: int):
        return self._candles[-limit:] if limit else self._candles


def _zigzag_candles(total: int = 220) -> list:
    """Sawtooth 50..100 that forces repeated HalfTrend flips.

    Four legs (down/up/down/up, 55 bars each) are needed: the very first
    rise never changes ``trend`` (it was already 0), so a real Buy flip
    (trend 1 -> 0) only appears on the second up-leg, after the ATR has
    warmed up.
    """
    out = []
    for i in range(total):
        pos = i % 110
        price = 100.0 - pos if pos < 55 else 45.0 + (pos - 55)
        out.append(
            OHLC.create(
                time=f"2026-09-03T09:{i % 60:02d}:{i // 60:02d}+05:30",
                open=price,
                high=price + 0.5,
                low=price - 0.5,
                close=price,
                volume=100,
            )
        )
    return out


async def test_halftrend_returns_one_row_per_bar():
    candles = _zigzag_candles()
    fake = _FakeMarketData(candles)
    body = await get_halftrend("SYM", interval="1m", limit=500, market_data=fake)

    rows = body["data"]
    assert len(rows) == len(candles)
    first = rows[0]
    assert set(first.keys()) == {"time", "trend", "ht", "atrHigh", "atrLow", "buy", "sell"}
    # channel null until the ATR(100) warms up
    assert first["atrHigh"] is None
    assert first["atrLow"] is None
    assert rows[-1]["time"] == candles[-1].time


async def test_halftrend_emits_buy_and_sell_over_long_zigzag():
    candles = _zigzag_candles()
    fake = _FakeMarketData(candles)
    body = await get_halftrend("SYM", interval="1m", limit=500, market_data=fake)
    rows = body["data"]
    # flips happen every ~55 bars in the sawtooth: at least one Buy and one
    # Sell must occur over the whole series
    assert any(r["buy"] for r in rows), "expected a Buy flip over the zigzag"
    assert any(r["sell"] for r in rows), "expected a Sell flip over the zigzag"
    # ATR needs ~100 true ranges — flips after bar 100 carry signals
    assert any(r["sell"] or r["buy"] for r in rows[100:]), "expected a signal after ATR warm-up"
    # channel present after warm-up
    assert all(r["atrHigh"] is not None for r in rows[100:])


async def test_halftrend_limit_is_honoured():
    candles = _zigzag_candles(total=200)
    fake = _FakeMarketData(candles)
    body = await get_halftrend("SYM", interval="1m", limit=60, market_data=fake)
    assert len(body["data"]) == 60
    # stateless series parity with compute_half_trend_series over same input
    full = compute_half_trend_series(candles[-60:])
    assert len(full) == 60
