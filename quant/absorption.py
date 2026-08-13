from dataclasses import dataclass, replace

from quant.bars import Bar

_BAR_BUFFER = 30
_AVG_WINDOW = 20
_MIN_BARS = 20


@dataclass(frozen=True)
class Absorption:
    bar_index: int
    price: float
    volume: float
    side: str            # "BUY" | "SELL"
    strength: float      # 0..1
    bar_age: int         # bars since this absorption (0 = current)


class AbsorptionDetector:
    def __init__(self, volume_mult: float = 1.5, range_ratio: float = 0.5) -> None:
        self._volume_mult = volume_mult
        self._range_ratio = range_ratio
        self._bars: list[Bar] = []
        self._index = 0
        self._current: Absorption | None = None

    def update(self, bar: Bar) -> None:
        window = self._bars[-_AVG_WINDOW:]
        avg_volume = sum(b.volume for b in window) / len(window) if window else 0.0
        avg_range = sum(b.high - b.low for b in window) / len(window) if window else 0.0

        self._bars.append(bar)
        if len(self._bars) > _BAR_BUFFER:
            del self._bars[:-_BAR_BUFFER]
        self._index += 1

        if self._index <= _MIN_BARS:
            return

        bar_range = bar.high - bar.low
        range_ok = avg_range > 0 and bar_range <= self._range_ratio * avg_range

        if avg_volume > 0 and bar.volume > self._volume_mult * avg_volume and range_ok:
            self._current = Absorption(
                bar_index=self._index - 1,
                price=bar.close,
                volume=bar.volume,
                side=self._side(bar),
                strength=self._strength(bar.volume, avg_volume),
                bar_age=0,
            )
        elif self._current is not None:
            self._current = replace(self._current, bar_age=self._current.bar_age + 1)

    def snapshot(self) -> Absorption | None:
        if self._index <= _MIN_BARS:
            return None
        return self._current

    @staticmethod
    def _side(bar: Bar) -> str:
        """Absorption side from the available volume mix.

        DATA CEILING: Dhan's WS feed carries no true aggressor/trade-flag
        split — ``buy_volume``/``sell_volume`` are tick-direction-attributed in
        the multiplexed feed (up-tick = buyer, down-tick = seller). The 55%%
        rule and the majority rule below therefore read the *direction-*
        attributed* mix, a documented proxy for Fabio's "big orders at a
        level" absorption (real order-flow prints are unavailable on Dhan).
        A bare candle-direction guess (close vs bar mid) is used only as the
        last resort on a tie, never as the primary signal.
        """
        vol = float(bar.volume or 0.0)
        buy = float(bar.buy_volume or 0.0)
        sell = float(bar.sell_volume or 0.0)
        if vol > 0:
            if buy >= 0.55 * vol:
                return "BUY"
            if sell >= 0.55 * vol:
                return "SELL"
            if buy != sell:
                return "BUY" if buy > sell else "SELL"
        mid = (bar.high + bar.low) / 2.0
        return "BUY" if bar.close > mid else "SELL"

    def _strength(self, volume: float, avg_volume: float) -> float:
        if avg_volume <= 0:
            return 0.0
        return min(1.0, (volume / avg_volume - 1) / 3)
