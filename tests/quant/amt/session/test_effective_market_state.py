"""Dead-volume veto: producer behaviour for option and futures series.

The DEAD market state is produced by exactly one place —
``compute_effective_market_state`` — and consumed by the Triple-A dead-market
rejection, the VA-fade refusal, the advisor narrative, and the ``DEAD_MARKET``
force-flatten. These tests pin the *producer*, at the function level and end to
end through ``AMTAnalyzer`` → ``amt_result_to_dto`` (the ``marketState`` field
the exit path reads), for both an option premium series and a futures series.
"""

from __future__ import annotations

from quant.amt.analyzer import AMTAnalyzer
from quant.amt.dto import amt_result_to_dto
from quant.amt.session.structure import (
    DEAD_PREMIUM_MIN_VOLUME,
    VOLUME_EMA_WINDOW,
    compute_effective_market_state,
)
from quant.contracts.enums import MarketState
from quant.contracts.value_objects import OHLC

OPTION_SYMBOL = "NIFTY 25000 CE"
FUTURES_SYMBOL = "NIFTY"

# A premium that trades steadily, zero-volume/zero price on the probed candle.
ALIVE_VOLUME = 4000.0
RATIO_COLLAPSED_VOLUME = 20.0  # 0.5% of the EMA — dead relatively, not absolutely
STOPPED_VOLUME = 5.0           # below DEAD_PREMIUM_MIN_VOLUME


def _candle(index: int, *, volume: float, close: float = 150.0) -> OHLC:
    """5-minute IST candle at 09:15 + index."""
    total = 15 + index * 5
    return OHLC(
        time=f"2026-01-01T{total // 60:02d}:{total % 60:02d}:00Z",
        open=close,
        high=close * 1.002,
        low=close * 0.998,
        close=close,
        volume=volume,
        vwap=close,
        taker_buy_volume=volume / 2,
        delta=0.0,
    )


def _series(*, latest_volume: float, count: int = VOLUME_EMA_WINDOW + 5, latest_close: float = 150.0) -> list[OHLC]:
    """Steady-volume series whose newest candle carries ``latest_volume``."""
    candles = [_candle(i, volume=ALIVE_VOLUME) for i in range(count - 1)]
    candles.append(_candle(count - 1, volume=latest_volume, close=latest_close))
    return candles


class TestDeadVolumeVeto:
    def test_quiet_premium_is_not_dead(self):
        """A thin premium candle is normal for the strike, not a dead auction."""
        data = _series(latest_volume=RATIO_COLLAPSED_VOLUME)

        assert (
            compute_effective_market_state(
                MarketState.BALANCED, data, data[-1], volume_scale="option"
            )
            == MarketState.BALANCED.value
        )

    def test_premium_that_stopped_trading_is_dead(self):
        data = _series(latest_volume=STOPPED_VOLUME)

        assert (
            compute_effective_market_state(
                MarketState.BALANCED, data, data[-1], volume_scale="option"
            )
            == MarketState.DEAD.value
        )

    def test_underlying_keeps_the_relative_veto(self):
        """Same numbers, futures scale: a ratio collapse is a dead auction."""
        data = _series(latest_volume=RATIO_COLLAPSED_VOLUME)

        assert (
            compute_effective_market_state(
                MarketState.BALANCED, data, data[-1], volume_scale="underlying"
            )
            == MarketState.DEAD.value
        )

    def test_forming_candle_is_never_judged(self):
        """A candle still filling must not read as collapsed volume."""
        data = _series(latest_volume=ALIVE_VOLUME, count=VOLUME_EMA_WINDOW + 5)
        forming = _candle(len(data), volume=0.0)
        data.append(forming)

        assert (
            compute_effective_market_state(
                MarketState.BALANCED, data, forming, latest_is_forming=True
            )
            == MarketState.BALANCED.value
        ), "the open candle was judged as volume"
        # Same series with the flag cleared, i.e. the caller swearing the newest
        # entry is closed: the veto fires. That is what keeps the flag load-bearing
        # instead of a no-op.
        assert (
            compute_effective_market_state(
                MarketState.BALANCED,
                data,
                forming,
                volume_scale="underlying",
                latest_is_forming=False,
            )
            == MarketState.DEAD.value
        )

    def test_forming_candle_at_the_window_boundary_is_not_judged(self):
        """At exactly VOLUME_EMA_WINDOW entries the newest is still forming.

        Only 19 candles are closed, so there is no complete EMA window and the
        veto must stay quiet — the boundary case that previously read the
        half-built candle as dead.
        """
        data = _series(latest_volume=0.0, count=VOLUME_EMA_WINDOW)

        assert (
            compute_effective_market_state(
                MarketState.BALANCED, data, data[-1], latest_is_forming=True
            )
            == MarketState.BALANCED.value
        )

    def test_short_series_leaves_state_untouched(self):
        data = _series(latest_volume=0.0, count=VOLUME_EMA_WINDOW - 1)

        assert (
            compute_effective_market_state(MarketState.IMBALANCED, data, data[-1])
            == MarketState.IMBALANCED.value
        )

    def test_non_positive_close_is_dead(self):
        data = _series(latest_volume=ALIVE_VOLUME, latest_close=0.0)

        assert (
            compute_effective_market_state(
                MarketState.BALANCED, data, data[-1], volume_scale="option"
            )
            == MarketState.DEAD.value
        )

    def test_premium_threshold_is_the_documented_boundary(self):
        just_alive = _series(latest_volume=DEAD_PREMIUM_MIN_VOLUME)
        stopped = _series(latest_volume=DEAD_PREMIUM_MIN_VOLUME - 1.0)

        assert (
            compute_effective_market_state(
                MarketState.BALANCED, just_alive, just_alive[-1], volume_scale="option"
            )
            != MarketState.DEAD.value
        )
        assert (
            compute_effective_market_state(
                MarketState.BALANCED, stopped, stopped[-1], volume_scale="option"
            )
            == MarketState.DEAD.value
        )


class TestDeadMarketProducer:
    """End to end: analyzer -> AMTResult -> DTO ``marketState``."""

    @staticmethod
    def _dto(symbol: str, data: list[OHLC], **kwargs) -> dict:
        result = AMTAnalyzer().analyze(data, symbol=symbol, **kwargs)
        return amt_result_to_dto(result)

    def test_option_premium_engine_can_still_report_dead_market(self):
        """Regression guard: DEAD must stay producible for an option symbol.

        Every production engine analyzes option-premium candles, so if the veto
        is skipped for options the Triple-A dead-market rejection and the
        DEAD_MARKET force-flatten become unreachable while the repo stays green.
        """
        data = _series(latest_volume=0.0)

        assert self._dto(OPTION_SYMBOL, data)["marketState"] == MarketState.DEAD.value

    def test_option_premium_quiet_strike_is_not_dead(self):
        data = _series(latest_volume=RATIO_COLLAPSED_VOLUME)

        assert self._dto(OPTION_SYMBOL, data)["marketState"] != MarketState.DEAD.value

    def test_futures_series_reports_dead_market(self):
        data = _series(latest_volume=RATIO_COLLAPSED_VOLUME)

        assert self._dto(FUTURES_SYMBOL, data)["marketState"] == MarketState.DEAD.value

    def test_forming_candle_does_not_dead_market_the_premium(self):
        data = _series(latest_volume=ALIVE_VOLUME)
        data.append(_candle(len(data), volume=0.0))

        dto = self._dto(OPTION_SYMBOL, data, latest_is_forming=True)

        assert dto["marketState"] != MarketState.DEAD.value
