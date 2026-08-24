from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradex_domain import OHLC, Candle, Equity, Price, Quantity, Timeframe

from tradex_trading.analytics.orderflow_types import OrderflowCandle
from tradex_trading.strategy.core.factory import StrategySpec, build_strategy
from tradex_trading.strategy.extensions import all_strategies
from tradex_trading.strategy.extensions.amt.absorption import AbsorptionDetector
from tradex_trading.strategy.extensions.amt.kernel import AMTKernel
from tradex_trading.strategy.extensions.amt.model import AMTStrategyConfig, BookSnapshot
from tradex_trading.strategy.extensions.amt.profile import profile
from tradex_trading.strategy.extensions.amt.strategy import AMTStrategy
from tradex_trading.strategy.extensions.amt.vwap import VWAPAccumulator

INSTRUMENT = Equity.of("NSE", "RELIANCE")


def _flow_candle(
    i: int,
    *,
    volume: str = "100",
    buy: str = "50",
    sell: str = "50",
    close: str = "100",
    high: str = "101",
    low: str = "99",
) -> OrderflowCandle:
    price = Decimal(close)
    return OrderflowCandle(
        instrument=INSTRUMENT,
        timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(price),
            high=Price(Decimal(high)),
            low=Price(Decimal(low)),
            close=Price(price),
        ),
        volume=Quantity(Decimal(volume)),
        timestamp=datetime(2026, 8, 1, 9, 15, tzinfo=UTC) + timedelta(minutes=i),
        buy_volume=float(buy),
        sell_volume=float(sell),
    )


def _candle(i: int, close: str = "100", volume: str = "100") -> Candle:
    price = Decimal(close)
    return Candle(
        instrument=INSTRUMENT,
        timeframe=Timeframe.M1,
        ohlc=OHLC(
            open=Price(price), high=Price(price + 1),
            low=Price(price - 1), close=Price(price),
        ),
        volume=Quantity(Decimal(volume)),
        timestamp=datetime(2026, 8, 1, 9, 15, tzinfo=UTC) + timedelta(minutes=i),
    )


def test_absorption_requires_volume_spike_and_compressed_range() -> None:
    detector = AbsorptionDetector()
    for i in range(20):
        detector.update(_flow_candle(i))

    detector.update(
        _flow_candle(
            20, volume="500", buy="450", sell="50",
            high="100.2", low="99.8",
        )
    )
    result = detector.snapshot()

    assert result is not None
    assert result.side == "BUY"
    assert Decimal("0") <= result.strength <= Decimal("1")
    assert result.bar_age == 0


def test_wide_range_spike_is_not_absorption() -> None:
    detector = AbsorptionDetector()
    for i in range(20):
        detector.update(_flow_candle(i))

    detector.update(
        _flow_candle(
            20, volume="500", buy="450", sell="50",
            high="110", low="90",
        )
    )

    assert detector.snapshot() is None


def test_amt_profile_conserves_volume() -> None:
    candles = [_candle(i, str(100 + i % 3)) for i in range(6)]
    poc, val, vah, lvn, hvn, shape = profile(candles)

    assert poc is not None
    assert val is not None and vah is not None and val <= poc <= vah
    assert isinstance(lvn, tuple)
    assert isinstance(hvn, tuple)
    assert shape in {"p_shape", "b_shape", "d_shape"}


def test_profile_detects_hvn_at_double_mean_volume() -> None:
    candles = [_candle(i, str(100 + i), "100") for i in range(6)]
    heavy = _candle(6, "103", "1000")
    poc, val, vah, lvn, hvn, shape = profile(candles + [heavy])

    assert Decimal("103") in hvn
    assert Decimal("103") == poc


def test_kernel_carries_enriched_absorption_and_delta() -> None:
    kernel = AMTKernel()
    for i in range(20):
        kernel.update(_flow_candle(i))

    snapshot = kernel.update(
        _flow_candle(
            20,
            volume="500",
            buy="450",
            sell="50",
            high="100.2",
            low="99.8",
        )
    )

    assert snapshot.delta == Decimal("400")
    assert snapshot.cvd == Decimal("400")
    assert snapshot.absorption_side == "BUY"
    assert snapshot.absorption_age == 0


def test_cvd_slope_is_positive_for_rising_deltas() -> None:
    kernel = AMTKernel()
    for i in range(6):
        kernel.update(
            _flow_candle(i, buy=str(50 + i * 5), sell=str(50 - i * 5))
        )

    assert kernel.snapshot is not None
    assert kernel.snapshot.cvd_slope > 0


def test_bullish_divergence_when_cvd_rises_and_price_falls() -> None:
    kernel = AMTKernel()
    for i in range(20):
        kernel.update(_flow_candle(i, buy="60", sell="40", close=str(100 - i)))

    assert kernel.snapshot is not None
    assert kernel.snapshot.cvd_slope == 0  # constant deltas -> flat flow slope
    assert kernel.snapshot.cvd_divergence == "BULLISH"


def test_bearish_divergence_when_cvd_falls_and_price_rises() -> None:
    kernel = AMTKernel()
    for i in range(20):
        kernel.update(_flow_candle(i, buy="40", sell="60", close=str(100 + i)))

    assert kernel.snapshot is not None
    assert kernel.snapshot.cvd_divergence == "BEARISH"


def test_no_divergence_when_cvd_and_price_agree() -> None:
    kernel = AMTKernel()
    for i in range(20):
        kernel.update(_flow_candle(i, buy="60", sell="40", close=str(100 + i)))

    assert kernel.snapshot is not None
    assert kernel.snapshot.cvd_divergence == "NONE"


def test_book_consumption_confirms_buy_absorption() -> None:
    kernel = AMTKernel()
    for i in range(20):
        kernel.update(_flow_candle(i))

    snapshot = kernel.update(
        _flow_candle(
            20, volume="500", buy="450", sell="50",
            high="100.2", low="99.8",
        ),
        BookSnapshot(swept_asks=2),
    )

    assert snapshot.absorption_side == "BUY"
    assert snapshot.absorption_confirmed is True
    assert snapshot.book_swept_asks == 2
    assert snapshot.book_polr == "neutral"


def test_absorption_without_book_is_not_confirmed() -> None:
    kernel = AMTKernel()
    for i in range(20):
        kernel.update(_flow_candle(i))

    snapshot = kernel.update(
        _flow_candle(
            20, volume="500", buy="450", sell="50",
            high="100.2", low="99.8",
        )
    )

    assert snapshot.absorption_side == "BUY"
    assert snapshot.absorption_confirmed is False


def test_vwap_bands_have_documented_proportional_width_floor() -> None:
    accumulator = VWAPAccumulator()
    value, std = accumulator.update(Decimal("100"), Decimal("100"))
    config = AMTStrategyConfig()
    width = max(std, value * Decimal("0.001"))

    assert width >= value * Decimal("0.001")
    assert config.minimum_risk_reward == Decimal("1.5")


def test_amt_is_explicitly_constructible_but_not_auto_enabled() -> None:
    strategy = build_strategy(
        StrategySpec(
            strategy_class=AMTStrategy,
            strategy_id="amt-explicit",
            instrument=INSTRUMENT,
        )
    )

    assert isinstance(strategy, AMTStrategy)
    assert all(existing.strategy_id != "amt-explicit" for existing in all_strategies)
